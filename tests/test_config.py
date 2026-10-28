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
    tabs = manager.snapshot()["tabs"]
    assert [t["label"] for t in tabs] == list("あかさたなはまやらわ")
    assert all(t["macros"] for t in tabs)
    assert tabs[0]["macros"][0]["id"] == "hello"
    assert ConfigManager(path).snapshot() == manager.snapshot()


def test_replacement_round_trip_and_snapshot_independence(tmp_path):
    path = tmp_path / "macros.json"
    manager = ConfigManager(path)
    raw = b'{"version": 1, "tabs": []}\n'
    manager.import_bytes(raw)
    assert manager.snapshot() == {"version": 1, "tabs": []}
    assert manager.export_bytes() == path.read_bytes() == raw
    snapshot = manager.snapshot()
    snapshot["tabs"].append({})
    assert manager.snapshot()["tabs"] == []
    assert path.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize(
    "raw",
    [
        b"{",
        b"\xff",
        b"[]",
        b'{"version":true,"tabs":[]}',
        b'{"version":2,"tabs":[]}',
        b'{"version":1,"tabs":{},"extra":1}',
        b'{"version":1,"version":1,"tabs":[]}',
        b'{"version":1,"macros":[]}',
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
    config["tabs"][0]["macros"][0].update(change)
    # ensure_ascii allows invalid-surrogate JSON to reach validation.
    with pytest.raises(ValidationError):
        manager.import_bytes(json.dumps(config).encode())


def test_duplicate_ids_are_rejected(tmp_path):
    manager = ConfigManager(tmp_path / "macros.json")
    config = manager.snapshot()
    config["tabs"][0]["macros"][1]["id"] = config["tabs"][0]["macros"][0]["id"]
    with pytest.raises(ValidationError, match="Duplicate macro id"):
        manager.import_bytes(encode(config))


def test_failed_atomic_replace_keeps_previous_config(tmp_path, monkeypatch):
    manager = ConfigManager(tmp_path / "macros.json")
    before = manager.export_bytes()

    def fail(*_):
        raise OSError("disk error")

    monkeypatch.setattr(os, "replace", fail)
    with pytest.raises(OSError):
        manager.import_bytes(b'{"version":1,"tabs":[]}')
    assert manager.export_bytes() == manager.path.read_bytes() == before
    assert list(tmp_path.glob(".macros-*")) == []


def test_corrupt_startup_file_is_not_silently_overwritten(tmp_path):
    path = tmp_path / "macros.json"
    path.write_bytes(b"{broken")
    with pytest.raises(ValidationError):
        ConfigManager(path)
    assert path.read_bytes() == b"{broken"


@pytest.mark.parametrize("tabs", [None, {}, "tabs", 3, False])
def test_tabs_must_be_an_array(tmp_path, tabs):
    manager = ConfigManager(tmp_path / "macros.json")
    with pytest.raises(ValidationError, match="tabs must be an array"):
        manager.import_bytes(encode({"version": 1, "tabs": tabs}))


@pytest.mark.parametrize(
    "change",
    [
        {"id": "../tab"},
        {"label": ""},
        {"label": "\ud800"},
        {"label": "line\nbreak"},
        {"label": "x" * 101},
        {"macros": {}},
        {"extra": 1},
    ],
)
def test_invalid_visible_tab_preserves_existing_configuration(tmp_path, change):
    manager = ConfigManager(tmp_path / "macros.json")
    raw = manager.export_bytes()
    config = manager.snapshot()
    config["tabs"][0].update(change)
    with pytest.raises(ValidationError, match=r"tabs\[0\]"):
        manager.import_bytes(json.dumps(config).encode())
    assert manager.export_bytes() == manager.path.read_bytes() == raw


def test_tab_ids_and_macro_ids_across_tabs_must_be_unique(tmp_path):
    manager = ConfigManager(tmp_path / "macros.json")
    config = manager.snapshot()
    config["tabs"][1]["id"] = config["tabs"][0]["id"]
    with pytest.raises(ValidationError, match="Duplicate tab id"):
        manager.import_bytes(encode(config))
    config = manager.snapshot()
    config["tabs"][1]["macros"][0]["id"] = config["tabs"][0]["macros"][0]["id"]
    with pytest.raises(ValidationError, match="Duplicate macro id"):
        manager.import_bytes(encode(config))


def test_each_tab_is_limited_to_one_hundred_macros(tmp_path):
    manager = ConfigManager(tmp_path / "macros.json")
    config = manager.snapshot()
    config["tabs"][0]["macros"] = [
        {"id": f"m{i}", "label": str(i), "steps": [{"type": "key", "value": "A"}]}
        for i in range(101)
    ]
    with pytest.raises(ValidationError, match="at most 100"):
        manager.import_bytes(encode(config))


@pytest.mark.parametrize(
    "ignored",
    [None, {"invalid": "not a tab"}, {"id": "bad", "label": "Bad", "macros": [{"invalid": True}]}],
)
def test_eleventh_and_later_tabs_are_ignored_without_losing_uploaded_bytes(tmp_path, ignored):
    path = tmp_path / "macros.json"
    manager = ConfigManager(path)
    config = manager.snapshot()
    assert len(config["tabs"]) == 10
    visible = manager.parse(encode(config))
    config["tabs"].extend([ignored, {"id": "also-ignored"}])
    raw = encode(config)
    manager.import_bytes(raw)
    assert manager.snapshot() == visible
    assert manager.export_bytes() == path.read_bytes() == raw
    assert ConfigManager(path).snapshot() == visible
    assert ConfigManager(path).export_bytes() == raw


def test_empty_tab_and_no_tabs_are_valid(tmp_path):
    manager = ConfigManager(tmp_path / "macros.json")
    config = {"version": 1, "tabs": [{"id": "empty", "label": "空", "macros": []}]}
    manager.import_bytes(encode(config))
    assert manager.snapshot() == config
    assert manager.get_macro("hello") is None
    manager.import_bytes(encode({"version": 1, "tabs": []}))
    assert manager.snapshot()["tabs"] == []


def test_visible_tab_limit_can_be_changed_in_one_place(tmp_path, monkeypatch):
    manager = ConfigManager(tmp_path / "macros.json")
    config = manager.snapshot()
    config["tabs"].append(
        {
            "id": "eleventh",
            "label": "11",
            "macros": [{"id": "hidden", "label": "11", "steps": [{"type": "key", "value": "A"}]}],
        }
    )
    raw = encode(config)
    manager.import_bytes(raw)
    assert manager.get_macro("hidden") is None
    monkeypatch.setattr("app.config_manager.MAX_VISIBLE_TABS", 11)
    manager.import_bytes(raw)
    assert len(manager.snapshot()["tabs"]) == 11
    assert manager.get_macro("hidden")["id"] == "hidden"


@pytest.mark.parametrize("index", [3, 9])
def test_newly_visible_tabs_are_validated(tmp_path, index):
    manager = ConfigManager(tmp_path / "macros.json")
    before = manager.export_bytes()
    config = manager.snapshot()
    config["tabs"][index]["macros"][0]["steps"] = [{"type": "text", "value": "かな"}]
    with pytest.raises(ValidationError, match=rf"tabs\[{index}\]"):
        manager.import_bytes(encode(config))
    assert manager.export_bytes() == before
