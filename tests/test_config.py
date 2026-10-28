import json
import os

import pytest

from app.config_manager import MAX_CONFIG_BYTES, ConfigManager
from app.macro_executor import ValidationError


def encode(config):
    return json.dumps(config, ensure_ascii=False).encode()


def test_missing_file_creates_persistent_sample(tmp_path):
    path = tmp_path / "nested" / "macros.json"
    manager = ConfigManager(path)
    assert path.exists()
    assert [m["id"] for m in manager.snapshot()["macros"]] == ["hello", "email", "form"]
    assert ConfigManager(path).snapshot() == manager.snapshot()


def test_replacement_round_trip_and_snapshot_independence(tmp_path):
    path = tmp_path / "macros.json"
    manager = ConfigManager(path)
    raw = b'{"version": 1, "macros": []}\n'
    manager.import_bytes(raw)
    assert manager.snapshot() == {"version": 1, "macros": []}
    assert manager.export_bytes() == path.read_bytes() == raw
    snapshot = manager.snapshot()
    snapshot["macros"].append({})
    assert manager.snapshot()["macros"] == []
    assert path.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize(
    "raw",
    [
        b"{",
        b"\xff",
        b"[]",
        b'{"version":true,"macros":[]}',
        b'{"version":2,"macros":[]}',
        b'{"version":1,"macros":{},"extra":1}',
        b'{"version":1,"version":1,"macros":[]}',
        b"[" * 2000,
        b" " * (MAX_CONFIG_BYTES + 1),
    ],
)
def test_invalid_import_preserves_existing_bytes(tmp_path, raw):
    manager = ConfigManager(tmp_path / "macros.json")
    before = manager.export_bytes()
    with pytest.raises(ValidationError):
        manager.import_bytes(raw)
    assert manager.export_bytes() == manager.path.read_bytes() == before


@pytest.mark.parametrize(
    "change",
    [
        {"id": "../x"},
        {"id": "hello", "steps": [{"type": "text", "value": "かな"}]},
        {"label": ""},
        {"label": "\ud800"},
        {"label": "line\nbreak"},
        {"steps": [{"type": "key", "value": "INVALID"}]},
        {"extra": 1},
    ],
)
def test_invalid_macro(tmp_path, change):
    manager = ConfigManager(tmp_path / "macros.json")
    config = manager.snapshot()
    config["macros"][0].update(change)
    # ensure_ascii allows invalid-surrogate JSON to reach validation.
    with pytest.raises(ValidationError):
        manager.import_bytes(json.dumps(config).encode())


def test_duplicate_ids_are_rejected(tmp_path):
    manager = ConfigManager(tmp_path / "macros.json")
    config = manager.snapshot()
    config["macros"][1]["id"] = config["macros"][0]["id"]
    with pytest.raises(ValidationError, match="Duplicate macro id"):
        manager.import_bytes(encode(config))


def test_failed_atomic_replace_keeps_previous_config(tmp_path, monkeypatch):
    manager = ConfigManager(tmp_path / "macros.json")
    before = manager.export_bytes()

    def fail(*_):
        raise OSError("disk error")

    monkeypatch.setattr(os, "replace", fail)
    with pytest.raises(OSError):
        manager.import_bytes(b'{"version":1,"macros":[]}')
    assert manager.export_bytes() == manager.path.read_bytes() == before
    assert list(tmp_path.glob(".macros-*")) == []


def test_corrupt_startup_file_is_not_silently_overwritten(tmp_path):
    path = tmp_path / "macros.json"
    path.write_bytes(b"{broken")
    with pytest.raises(ValidationError):
        ConfigManager(path)
    assert path.read_bytes() == b"{broken"
