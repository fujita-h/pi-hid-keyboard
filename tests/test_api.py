import base64
import io
import json
import re

import pytest
from itsdangerous import URLSafeTimedSerializer
from werkzeug.datastructures import MultiDict
from werkzeug.security import check_password_hash, generate_password_hash

from app.hid_keyboard import HIDError, USLayout
from app.main import create_app


@pytest.mark.parametrize(
    "path", ["/", "/input", "/api/macros", "/api/status", "/api/config/export", "/static/app.js"]
)
def test_all_reads_require_authentication(client, path):
    response = client.get(path)
    assert response.status_code == 401
    assert "Basic" in response.headers["WWW-Authenticate"]


def test_wrong_password_rejected(client):
    token = base64.b64encode(b"tester:wrong").decode()
    assert client.get("/", headers={"Authorization": f"Basic {token}"}).status_code == 401
    assert client.get_cookie("keybridge_session") is None


def test_password_checked_once_for_browser_session(client, auth, keyboard, monkeypatch):
    checks = []

    def count_check(stored, supplied):
        checks.append(True)
        return check_password_hash(stored, supplied)

    monkeypatch.setattr("app.main.check_password_hash", count_check)
    response = client.get("/", headers=auth)
    assert response.status_code == 200
    cookie = client.get_cookie("keybridge_session")
    assert cookie.http_only
    assert cookie.same_site == "Strict"
    assert cookie.expires is not None
    token = re.search(r'name="csrf-token" content="([^\"]+)"', response.get_data(as_text=True))[1]

    # Browsers may keep sending cached Basic credentials alongside the cookie.
    for headers in ({}, auth):
        for path in (
            "/",
            "/input",
            "/static/app.js",
            "/api/macros",
            "/api/status",
            "/api/config/export",
        ):
            response = client.get(path, headers=headers)
            assert response.status_code == 200
            assert "Set-Cookie" not in response.headers
        assert (
            client.post(
                "/api/macros/hello/execute", headers={**headers, "X-CSRF-Token": token}
            ).status_code
            == 200
        )
    assert len(checks) == 1
    assert len(keyboard.reports) == 2 * len("Hello World!")


def test_session_alone_still_requires_csrf(client, headers, keyboard):
    path = "/api/macros/hello/execute"
    assert client.post(path).status_code == 403
    assert client.post(path, headers={"X-CSRF-Token": "forged"}).status_code == 403
    assert (
        client.post(
            path,
            headers={"X-CSRF-Token": headers["X-CSRF-Token"], "Sec-Fetch-Site": "cross-site"},
        ).status_code
        == 403
    )
    assert keyboard.reports == []


def test_session_expires_without_sliding_and_basic_renews_it(client, auth, monkeypatch):
    now = 1700000000
    monkeypatch.setattr("itsdangerous.timed.TimestampSigner.get_timestamp", lambda self: now)
    checks = []

    def count_check(stored, supplied):
        checks.append(True)
        return check_password_hash(stored, supplied)

    monkeypatch.setattr("app.main.check_password_hash", count_check)
    assert client.get("/", headers=auth).status_code == 200
    now += 1800
    response = client.get("/api/status")
    assert response.status_code == 200
    assert "Set-Cookie" not in response.headers
    now += 1801
    assert client.get("/api/status").status_code == 401
    assert len(checks) == 1
    assert client.get("/api/status", headers=auth).status_code == 200
    assert len(checks) == 2
    assert client.get("/api/status").status_code == 200


def test_forged_session_rejected_and_basic_can_recover(client, auth):
    assert client.get("/", headers=auth).status_code == 200
    cookie = client.get_cookie("keybridge_session").value
    client.set_cookie("keybridge_session", cookie + "tampered")
    assert client.get("/api/status").status_code == 401
    assert client.get("/api/status", headers=auth).status_code == 200
    assert client.get("/api/status").status_code == 200


@pytest.mark.parametrize("changed", [None, "username", "password", "secret"])
def test_sessions_survive_restart_only_with_same_credentials(client, auth, app, keyboard, changed):
    assert client.get("/", headers=auth).status_code == 200
    config = dict(app.config)
    if changed == "username":
        config["AUTH_USERNAME"] = "new-user"
    elif changed == "password":
        config["AUTH_PASSWORD_HASH"] = generate_password_hash(
            "new-password", method="pbkdf2:sha256:1000"
        )
    elif changed == "secret":
        config["SECRET_KEY"] = "n" * 64
    fresh_client = create_app(config, keyboard=keyboard).test_client()
    fresh_client.set_cookie("keybridge_session", client.get_cookie("keybridge_session").value)
    assert fresh_client.get("/api/status").status_code == (401 if changed else 200)


def test_wrong_username_skips_password_hashing(client, monkeypatch):
    def unexpected_check(*_):
        pytest.fail("Unknown usernames should not trigger password hashing")

    monkeypatch.setattr("app.main.check_password_hash", unexpected_check)
    token = base64.b64encode(b"unknown:test-password").decode()
    assert client.get("/", headers={"Authorization": f"Basic {token}"}).status_code == 401


def test_index_macros_status_and_security_headers(client, headers):
    response = client.get("/", headers=headers)
    assert response.status_code == 200
    assert response.headers["X-Frame-Options"] == "DENY"
    assert "no-store" in response.headers["Cache-Control"]
    assert "script-src 'self'" in response.headers["Content-Security-Policy"]
    assert b'role="tablist"' not in response.data
    assert b'role="tabpanel"' not in response.data
    tabs = client.get("/api/macros", headers=headers).json["tabs"]
    assert [t["label"] for t in tabs] == list("あかさたなはまやらわ")
    macros = [m for tab in tabs for m in tab["macros"]]
    assert [m["id"] for m in macros[:3]] == ["hello", "email", "form"]
    assert len(macros) == 19
    assert "steps" not in macros[0]
    assert client.get("/api/status", headers=headers).json["busy"] is False


def test_input_only_page_keeps_authenticated_execution_without_settings(client, auth, keyboard):
    response = client.get("/input", headers=auth)
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'class="input-only"' in html
    assert 'class="compact-grid"' in html
    assert 'class="toast"' in html
    assert 'aria-live="polite"' in html
    assert 'id="import"' not in html
    assert 'id="file"' not in html
    assert "<h1" not in html
    assert 'href="/input"' in client.get("/").get_data(as_text=True)
    token = re.search(r'name="csrf-token" content="([^"]+)"', html)[1]
    assert client.post("/api/macros/hello/execute").status_code == 403
    response = client.post("/api/macros/hello/execute", headers={"X-CSRF-Token": token})
    assert response.status_code == 200
    assert len(keyboard.reports) == len("Hello World!")


def test_hundred_macros_preserve_json_order_and_only_expose_button_metadata(client, headers, app):
    tabs = [
        {
            "id": f"tab-{n}",
            "label": f"分類 {n}",
            "macros": [
                {
                    "id": f"macro-{n}-{i}",
                    "label": f"定型入力 {i}",
                    "steps": [{"type": "key", "value": "A"}],
                }
                for i in reversed(range(100))
            ],
        }
        for n in reversed(range(10))
    ]
    app.extensions["config_manager"].import_bytes(json.dumps({"version": 1, "tabs": tabs}).encode())
    response = client.get("/api/macros", headers=headers)
    assert response.status_code == 200
    assert response.json == {
        "version": 1,
        "tabs": [
            {
                "id": t["id"],
                "label": t["label"],
                "macros": [{"id": m["id"], "label": m["label"]} for m in t["macros"]],
            }
            for t in tabs
        ],
    }


def test_eleventh_tab_is_preserved_in_export_but_not_listed_or_executable(
    client, headers, app, keyboard
):
    tabs = app.extensions["config_manager"].snapshot()["tabs"]
    tabs.extend(
        [
            {
                "id": "ignored",
                "label": "非表示",
                "macros": [
                    {"id": "hidden", "label": "非表示", "steps": [{"type": "key", "value": "B"}]}
                ],
            },
        ]
    )
    raw = json.dumps({"version": 1, "tabs": tabs}).encode()
    response = client.post(
        "/api/config/import", headers=headers, data={"file": (io.BytesIO(raw), "tabs.json")}
    )
    assert response.status_code == 200
    assert response.json == {"ok": True, "count": 19, "tab_count": 10}
    assert [t["id"] for t in client.get("/api/macros", headers=headers).json["tabs"]] == [
        t["id"] for t in tabs[:10]
    ]
    assert client.get("/api/config/export", headers=headers).data == raw
    assert client.post("/api/macros/hidden/execute", headers=headers).status_code == 404
    assert client.post("/api/macros/ta-1/execute", headers=headers).status_code == 200
    assert client.post("/api/macros/wa-2/execute", headers=headers).status_code == 200
    assert keyboard.reports


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
    raw = b'{ "version": 1, "tabs": [] }\n'
    response = client.post(
        "/api/config/import", headers=headers, data={"file": (io.BytesIO(raw), "macros.json")}
    )
    assert response.status_code == 200
    assert client.get("/api/macros", headers=headers).json["tabs"] == []
    exported = client.get("/api/config/export", headers=headers)
    assert exported.data == raw
    assert "filename=macros.json" in exported.headers["Content-Disposition"]
    fresh = create_app(dict(app.config), keyboard=keyboard)
    assert fresh.extensions["config_manager"].snapshot()["tabs"] == []


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
    value = b'{"version":1,"tabs":[]}'
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
                ("file", (io.BytesIO(b'{"version":1,"tabs":[]}'), "a.json")),
                ("file", (io.BytesIO(b'{"version":1,"tabs":[]}'), "b.json")),
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
        data={"file": (io.BytesIO(b'{"version":1,"tabs":[]}'), "x.json")},
    )
    assert response.status_code == 500
    assert manager.export_bytes() == before


def test_unsafe_label_is_kept_as_data(client, headers):
    config = {
        "version": 1,
        "tabs": [
            {
                "id": "test",
                "label": "<b>タブ名</b>",
                "macros": [
                    {
                        "id": "x",
                        "label": "<script>alert(1)</script>",
                        "steps": [{"type": "key", "value": "A"}],
                    }
                ],
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
        client.get("/api/macros", headers=headers)
        .json["tabs"][0]["macros"][0]["label"]
        .startswith("<script>")
    )


def test_secure_defaults_fail_closed(tmp_path, monkeypatch):
    for name in ("KEYBRIDGE_USERNAME", "KEYBRIDGE_PASSWORD_HASH", "KEYBRIDGE_SECRET_KEY"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(RuntimeError, match="credentials"):
        create_app({"CONFIG_PATH": tmp_path / "macros.json"})


def test_timing_multipliers_from_environment_reach_validation_and_keyboard(app, monkeypatch):
    monkeypatch.setenv("KEYBRIDGE_KEY_HOLD_MAX_MULTIPLIER", "1.5")
    monkeypatch.setenv("KEYBRIDGE_KEY_INTERVAL_MAX_MULTIPLIER", "2.0")
    config = dict(app.config)
    config.pop("KEY_HOLD_MAX_MULTIPLIER")
    config.pop("KEY_INTERVAL_MAX_MULTIPLIER")
    config["KEY_INTERVAL_MS"] = 20
    fresh = create_app(config)
    compiler = fresh.extensions["macro_executor"].compiler
    keyboard = fresh.extensions["keyboard"]
    assert compiler.hold_timing.seconds == keyboard.hold_timing.seconds == 0.02
    assert compiler.hold_timing.max_seconds == keyboard.hold_timing.max_seconds == 0.03
    assert compiler.interval_timing.seconds == 0.02
    assert compiler.interval_timing.max_seconds == 0.04


def test_existing_environment_without_multipliers_keeps_fixed_timings(app, monkeypatch):
    config = dict(app.config)
    for setting in ("KEY_HOLD_MAX_MULTIPLIER", "KEY_INTERVAL_MAX_MULTIPLIER"):
        config.pop(setting)
        monkeypatch.delenv("KEYBRIDGE_" + setting, raising=False)
    config["KEY_INTERVAL_MS"] = 20
    fresh = create_app(config)
    compiler = fresh.extensions["macro_executor"].compiler
    keyboard = fresh.extensions["keyboard"]
    for timing in (compiler.hold_timing, compiler.interval_timing, keyboard.hold_timing):
        assert timing.seconds == timing.max_seconds == timing.sample() == 0.02


@pytest.mark.parametrize("setting", ["KEY_HOLD_MAX_MULTIPLIER", "KEY_INTERVAL_MAX_MULTIPLIER"])
@pytest.mark.parametrize("value", ["0.5", "nan", "inf", "invalid", "100"])
def test_invalid_timing_multiplier_prevents_startup(app, setting, value):
    with pytest.raises(ValueError):
        create_app({**app.config, "KEY_INTERVAL_MS": 20, setting: value})
