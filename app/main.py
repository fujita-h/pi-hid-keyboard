"""Authenticated Flask API. Production uses one process with multiple threads."""

import hmac
import io
import os
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_file
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from werkzeug.exceptions import HTTPException
from werkzeug.security import check_password_hash

from app.config_manager import MAX_CONFIG_BYTES, ConfigManager
from app.hid_keyboard import HIDError, HIDKeyboard
from app.macro_executor import BusyError, MacroCompiler, MacroExecutor, ValidationError

ROOT = Path(__file__).resolve().parent.parent


def create_app(config=None, *, keyboard=None):
    app = Flask(__name__)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("KEYBRIDGE_SECRET_KEY"),
        AUTH_USERNAME=os.environ.get("KEYBRIDGE_USERNAME"),
        AUTH_PASSWORD_HASH=os.environ.get("KEYBRIDGE_PASSWORD_HASH"),
        CONFIG_PATH=os.environ.get("KEYBRIDGE_CONFIG", str(ROOT / "data" / "macros.json")),
        HID_DEVICE=os.environ.get("KEYBRIDGE_HID_DEVICE", "/dev/hidg0"),
        KEY_INTERVAL_MS=os.environ.get("KEYBRIDGE_KEY_INTERVAL_MS", "20"),
        KEY_HOLD_MS=os.environ.get("KEYBRIDGE_KEY_HOLD_MS", "20"),
        MAX_CONTENT_LENGTH=MAX_CONFIG_BYTES + 16 * 1024,
        # Werkzeug also applies this limit to its multipart decoder buffer,
        # including file chunks. Keep it large enough for a valid 256 KiB file.
        MAX_FORM_MEMORY_SIZE=MAX_CONFIG_BYTES + 16 * 1024,
        MAX_FORM_PARTS=4,
    )
    if config:
        app.config.update(config)
    if not all(app.config.get(k) for k in ("SECRET_KEY", "AUTH_USERNAME", "AUTH_PASSWORD_HASH")):
        raise RuntimeError("Set KeyBridge credentials and secret using scripts/configure-auth.py")
    if len(app.config["SECRET_KEY"]) < 32:
        raise RuntimeError("KEYBRIDGE_SECRET_KEY must contain at least 32 characters")

    compiler = MacroCompiler(
        interval_ms=float(app.config["KEY_INTERVAL_MS"]), hold_ms=float(app.config["KEY_HOLD_MS"])
    )
    keyboard = keyboard or HIDKeyboard(
        app.config["HID_DEVICE"], hold_ms=float(app.config["KEY_HOLD_MS"])
    )
    manager = ConfigManager(app.config["CONFIG_PATH"], compiler)
    executor = MacroExecutor(keyboard, compiler)
    signer = URLSafeTimedSerializer(app.config["SECRET_KEY"], salt="keybridge-csrf-v1")
    app.extensions.update(config_manager=manager, macro_executor=executor, keyboard=keyboard)

    def error(message, code, status):
        return jsonify(error={"code": code, "message": message}), status

    @app.before_request
    def authenticate_and_check_csrf():
        auth = request.authorization
        valid = False
        if auth and auth.type == "basic" and auth.username and auth.password is not None:
            valid_user = hmac.compare_digest(
                auth.username.encode(), app.config["AUTH_USERNAME"].encode()
            )
            valid_password = check_password_hash(app.config["AUTH_PASSWORD_HASH"], auth.password)
            valid = valid_user and valid_password
        if not valid:
            response, status = error("Authentication required", "unauthorized", 401)
            response.headers["WWW-Authenticate"] = 'Basic realm="KeyBridge", charset="UTF-8"'
            return response, status
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            try:
                user = signer.loads(request.headers.get("X-CSRF-Token", ""), max_age=3600)
                if user != app.config["AUTH_USERNAME"]:
                    raise BadSignature("Wrong user")
            except (BadSignature, SignatureExpired):
                return error("CSRF token missing or expired; reload the page", "csrf", 403)
            if request.headers.get("Sec-Fetch-Site") == "cross-site":
                return error("Cross-site requests are not allowed", "csrf", 403)

    @app.after_request
    def secure_headers(response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self'; connect-src 'self'; object-src 'none'; "
            "base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
        )
        return response

    @app.errorhandler(ValidationError)
    def invalid_config(exc):
        return error(str(exc), "invalid_config", 400)

    @app.errorhandler(BusyError)
    def busy_error(exc):
        return error(str(exc), "busy", 409)

    @app.errorhandler(HIDError)
    def hid_error(exc):
        app.logger.warning("HID execution failed: %s", exc)
        return error(str(exc), "hid_unavailable", 503)

    @app.errorhandler(HTTPException)
    def http_error(exc):
        return error(exc.description, exc.name.lower().replace(" ", "_"), exc.code)

    @app.errorhandler(OSError)
    def storage_error(exc):
        app.logger.exception("Configuration storage failed")
        return error("Cannot read/write configuration; check disk and permissions", "storage", 500)

    @app.get("/")
    def index():
        return render_template("index.html", csrf_token=signer.dumps(app.config["AUTH_USERNAME"]))

    @app.get("/api/macros")
    def macros():
        # The browser only needs button metadata, not potentially sensitive text.
        return jsonify(
            version=1,
            macros=[{"id": m["id"], "label": m["label"]} for m in manager.snapshot()["macros"]],
        )

    @app.post("/api/macros/<macro_id>/execute")
    def execute(macro_id):
        macro = manager.get_macro(macro_id)
        if macro is None:
            return error("Macro not found", "not_found", 404)
        executor.execute(macro["steps"])
        return jsonify(ok=True, id=macro_id)

    @app.post("/api/config/import")
    def import_config():
        if (
            list(request.files) != ["file"]
            or len(request.files.getlist("file")) != 1
            or request.form
        ):
            raise ValidationError("Upload exactly one JSON file using the file field")
        uploaded = request.files["file"]
        if not uploaded.filename or not uploaded.filename.lower().endswith(".json"):
            raise ValidationError("Select a .json file")
        # The filename is never used as a filesystem path.
        manager.import_bytes(uploaded.stream.read(MAX_CONFIG_BYTES + 1))
        return jsonify(ok=True, count=len(manager.snapshot()["macros"]))

    @app.get("/api/config/export")
    def export_config():
        return send_file(
            io.BytesIO(manager.export_bytes()),
            mimetype="application/json",
            as_attachment=True,
            download_name="macros.json",
            max_age=0,
        )

    @app.get("/api/status")
    def status():
        return jsonify(hid=keyboard.status(), busy=executor.busy, layout=compiler.layout.name)

    return app


if __name__ == "__main__":
    # Development only. Production runs under the unprivileged systemd user.
    create_app().run(host="127.0.0.1", port=8000, threaded=True, debug=False)
