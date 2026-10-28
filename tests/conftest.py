import base64
import contextlib
import re

import pytest
from werkzeug.security import generate_password_hash

from app.main import create_app


class FakeKeyboard:
    def __init__(self):
        self.reports = []
        self.sessions = 0
        self.available = True

    @contextlib.contextmanager
    def session(self):
        self.sessions += 1
        yield self

    def tap(self, report):
        self.reports.append(report)

    def status(self):
        return {
            "device_exists": self.available,
            "writable": self.available,
            "connected": self.available,
            "udc_states": {},
            "ready": self.available,
        }


@pytest.fixture
def keyboard():
    return FakeKeyboard()


@pytest.fixture
def app(tmp_path, keyboard):
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "s" * 64,
            "AUTH_USERNAME": "tester",
            "AUTH_PASSWORD_HASH": generate_password_hash(
                "test-password", method="pbkdf2:sha256:1000"
            ),
            "CONFIG_PATH": tmp_path / "macros.json",
            "KEY_INTERVAL_MS": 0,
        },
        keyboard=keyboard,
    )
    return app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def auth():
    value = base64.b64encode(b"tester:test-password").decode()
    return {"Authorization": f"Basic {value}"}


@pytest.fixture
def headers(client, auth):
    html = client.get("/", headers=auth).get_data(as_text=True)
    token = re.search(r'name="csrf-token" content="([^"]+)"', html)[1]
    return {**auth, "X-CSRF-Token": token}
