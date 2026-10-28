import base64
import io
import json

import pytest
from itsdangerous import URLSafeTimedSerializer
from werkzeug.datastructures import MultiDict

from app.hid_keyboard import HIDError, USLayout
from app.main import create_app


@pytest.mark.parametrize(
    "path", ["/", "/api/macros", "/api/status", "/api/config/export", "/static/app.js"]
)
def test_all_reads_require_authentication(client, path):
    response = client.get(path)
    assert response.status_code == 401
    assert "Basic" in response.headers["WWW-Authenticate"]


def test_wrong_password_rejected(client):
    token = base64.b64encode(b"tester:wrong").decode()
    assert client.get("/", headers={"Authorization": f"Basic {token}"}).status_code == 401


def test_index_macros_status_and_security_headers(client, headers):
    response = client.get("/", headers=headers)
    assert response.status_code == 200
    assert response.headers["X-Frame-Options"] == "DENY"
    assert "no-store" in response.headers["Cache-Control"]
    assert "script-src 'self'" in response.headers["Content-Security-Policy"]
    macros = client.get("/api/macros", headers=headers).json["macros"]
    assert [m["id"] for m in macros] == ["hello", "email", "form"]
    assert "steps" not in macros[0]
    assert client.get("/api/status", headers=headers).json["busy"] is False


@pytest.mark.parametrize("path", ["/api/macros/hello/execute", "/api/config/import"])
def test_mutations_require_auth_and_csrf(client, auth, path):
    assert client.post(path).status_code == 401
    assert client.post(path, headers=auth).status_code == 403
    assert client.post(path, headers={**auth, "X-CSRF-Token": "forged"}).status_code == 403


def test_csrf_wrong_user_expired_and_cross_site(client, headers, app, monkeypatch):
    path = "/api/macros/hello/execute"
    signer = URLSafeTimedSerializer(app.config["SECRET_KEY"], salt="keybridge-csrf-v1")
    assert (
        client.post(path, headers={**headers, "X-CSRF-Token": signer.dumps("other")}).status_code
        == 403
    )
    assert client.post(path, headers={**headers, "Sec-Fetch-Site": "cross-site"}).status_code == 403
    monkeypatch.setattr("itsdangerous.timed.TimestampSigner.get_timestamp", lambda self: 1)
    token = signer.dumps("tester")
    monkeypatch.undo()
    assert client.post(path, headers={**headers, "X-CSRF-Token": token}).status_code == 403


def test_execute_registered_macro_only(client, headers, keyboard):
    response = client.post(
        "/api/macros/hello/execute",
        headers=headers,
        json={"steps": [{"type": "text", "value": "untrusted"}]},
    )
    assert response.status_code == 200
    assert keyboard.reports == [USLayout().character(c) for c in "Hello World!"]
    assert client.post("/api/macros/unknown/execute", headers=headers).status_code == 404
    assert client.post("/api/execute", headers=headers).status_code == 404


def test_import_export_exact_bytes_and_restarts(client, headers, app, keyboard):
    raw = b'{ "version": 1, "macros": [] }\n'
    response = client.post(
        "/api/config/import", headers=headers, data={"file": (io.BytesIO(raw), "macros.json")}
    )
    assert response.status_code == 200
    assert client.get("/api/macros", headers=headers).json["macros"] == []
    exported = client.get("/api/config/export", headers=headers)
    assert exported.data == raw
    assert "filename=macros.json" in exported.headers["Content-Disposition"]
    fresh = create_app(dict(app.config), keyboard=keyboard)
    assert fresh.extensions["config_manager"].snapshot()["macros"] == []


@pytest.mark.parametrize(("name", "raw"), [("wrong.txt", b"{}"), ("macros.json", b"{bad")])
def test_invalid_import_keeps_old_data(client, headers, name, raw):
    before = client.get("/api/config/export", headers=headers).data
    result = client.post(
        "/api/config/import", headers=headers, data={"file": (io.BytesIO(raw), name)}
    )
    assert result.status_code == 400
    assert client.get("/api/config/export", headers=headers).data == before


def test_oversized_upload_and_missing_file(client, headers):
    assert client.post("/api/config/import", headers=headers).status_code == 400
    response = client.post(
        "/api/config/import",
        headers=headers,
        data={"file": (io.BytesIO(b" " * (300 * 1024)), "big.json")},
    )
    assert response.status_code == 413


@pytest.mark.parametrize("size", [32 * 1024, 256 * 1024, 256 * 1024 + 1])
def test_upload_accepts_full_documented_file_limit(client, headers, size):
    value = b'{"version":1,"macros":[]}'
    raw = b" " * (size - len(value)) + value
    before = client.get("/api/config/export", headers=headers).data
    response = client.post(
        "/api/config/import",
        headers=headers,
        data={"file": (io.BytesIO(raw), "macros.json")},
    )
    if size <= 256 * 1024:
        assert response.status_code == 200
        assert client.get("/api/config/export", headers=headers).data == raw
    else:
        assert response.status_code == 400
        assert client.get("/api/config/export", headers=headers).data == before


def test_duplicate_file_fields_are_rejected(client, headers):
    response = client.post(
        "/api/config/import",
        headers=headers,
        data=MultiDict(
            [
                ("file", (io.BytesIO(b'{"version":1,"macros":[]}'), "a.json")),
                ("file", (io.BytesIO(b'{"version":1,"macros":[]}'), "b.json")),
            ]
        ),
    )
    assert response.status_code == 400


def test_usb_error_returns_503_and_web_survives(client, headers, keyboard):
    def fail(_):
        raise HIDError("Disconnected")

    keyboard.tap = fail
    response = client.post("/api/macros/hello/execute", headers=headers)
    assert response.status_code == 503
    assert response.json["error"]["code"] == "hid_unavailable"
    assert client.get("/api/status", headers=headers).status_code == 200


def test_busy_response(client, headers, app):
    executor = app.extensions["macro_executor"]
    executor._lock.acquire()
    try:
        assert client.post("/api/macros/hello/execute", headers=headers).status_code == 409
    finally:
        executor._lock.release()


def test_storage_error_does_not_replace_live_config(client, headers, app, monkeypatch):
    manager = app.extensions["config_manager"]
    before = manager.export_bytes()

    def fail(*_):
        raise OSError("disk full")

    monkeypatch.setattr("app.config_manager.os.replace", fail)
    response = client.post(
        "/api/config/import",
        headers=headers,
        data={"file": (io.BytesIO(b'{"version":1,"macros":[]}'), "x.json")},
    )
    assert response.status_code == 500
    assert manager.export_bytes() == before


def test_unsafe_label_is_kept_as_data(client, headers):
    config = {
        "version": 1,
        "macros": [
            {
                "id": "x",
                "label": "<script>alert(1)</script>",
                "steps": [{"type": "key", "value": "A"}],
            }
        ],
    }
    response = client.post(
        "/api/config/import",
        headers=headers,
        data={"file": (io.BytesIO(json.dumps(config).encode()), "x.json")},
    )
    assert response.status_code == 200
    assert b"<script>alert" not in client.get("/", headers=headers).data
    assert (
        client.get("/api/macros", headers=headers).json["macros"][0]["label"].startswith("<script>")
    )


def test_secure_defaults_fail_closed(tmp_path, monkeypatch):
    for name in ("KEYBRIDGE_USERNAME", "KEYBRIDGE_PASSWORD_HASH", "KEYBRIDGE_SECRET_KEY"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(RuntimeError, match="credentials"):
        create_app({"CONFIG_PATH": tmp_path / "macros.json"})
