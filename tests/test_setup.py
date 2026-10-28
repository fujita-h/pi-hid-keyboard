import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "configure_boot", Path(__file__).resolve().parents[1] / "scripts/configure-boot.py"
)
boot = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(boot)


def test_boot_change_preserves_original_and_is_idempotent(tmp_path):
    path = tmp_path / "config.txt"
    original = "# existing\ndtparam=audio=on\n[pi4]\nmax_framebuffers=2\n"
    path.write_text(original)
    assert boot.configure(path)
    assert path.with_name("config.txt.keybridge.bak").read_text() == original
    assert path.read_text().startswith(original)
    assert boot.BLOCK in path.read_text()
    assert not boot.configure(path)


def test_boot_dry_run_makes_no_changes(tmp_path):
    path = tmp_path / "config.txt"
    path.write_text("# original\n")
    assert boot.configure(path, dry_run=True)
    assert path.read_text() == "# original\n"
    assert len(list(tmp_path.iterdir())) == 1


@pytest.mark.parametrize(
    "line", ["dtoverlay=dwc2", "dtoverlay=dwc2,dr_mode=host", "dtoverlay=dwc-otg"]
)
def test_existing_controller_overlay_requires_manual_reconciliation(tmp_path, line):
    path = tmp_path / "config.txt"
    path.write_text(line + "\n")
    with pytest.raises(ValueError, match="Existing USB controller"):
        boot.configure(path)
    assert path.read_text() == line + "\n"


def test_modified_managed_block_is_preserved(tmp_path):
    path = tmp_path / "config.txt"
    path.write_text(boot.BLOCK.replace("peripheral", "host"))
    with pytest.raises(ValueError, match="Modified KeyBridge"):
        boot.configure(path)
