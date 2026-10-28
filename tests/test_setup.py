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


def test_default_os_other_model_overlays_are_preserved(tmp_path):
    path = tmp_path / "config.txt"
    original = (
        "dtparam=audio=on\n[cm4]\notg_mode=1\n"
        "[cm5]\ndtoverlay=dwc2,dr_mode=host\n"
        "[pi5]\ndtoverlay=nospi10\n[all]\n"
    )
    path.write_text(original)
    assert boot.configure(path)
    assert path.read_text() == original + "\n" + boot.BLOCK
    assert path.with_name("config.txt.keybridge.bak").read_text() == original
    assert not boot.configure(path)


@pytest.mark.parametrize("condition", ["cm4", "cm5", "pi3", "pi4", "pi5", "none"])
def test_inapplicable_overlay_does_not_block_install(tmp_path, condition):
    path = tmp_path / "config.txt"
    path.write_text(f"[{condition}]\ndtoverlay=dwc2,dr_mode=host\n")
    assert boot.configure(path)


@pytest.mark.parametrize("condition", ["all", "pi0", "pi0w", "pi02", "gpio4=1", "0x12345678"])
def test_applicable_or_uncertain_overlay_still_requires_review(tmp_path, condition):
    path = tmp_path / "config.txt"
    original = f"[{condition}]\ndtoverlay=dwc2,dr_mode=host\n"
    path.write_text(original)
    with pytest.raises(ValueError, match="line 2"):
        boot.configure(path)
    assert path.read_text() == original
    assert not path.with_name("config.txt.keybridge.bak").exists()


@pytest.mark.parametrize("reset", ["all", "pi02"])
def test_model_filter_change_can_make_overlay_apply(tmp_path, reset):
    path = tmp_path / "config.txt"
    path.write_text(f"[cm5]\ndtoverlay=dwc2,dr_mode=host\n[{reset}]\ndtoverlay=dwc2\n")
    with pytest.raises(ValueError, match="line 4"):
        boot.configure(path)


def test_additional_filter_cannot_enable_another_board_model(tmp_path):
    path = tmp_path / "config.txt"
    path.write_text("[cm5]\n[gpio4=1]\ndtoverlay=dwc2,dr_mode=host\n")
    assert boot.configure(path)


def test_managed_block_does_not_hide_conflict_after_its_all_reset(tmp_path):
    path = tmp_path / "config.txt"
    path.write_text("[cm5]\n" + boot.BLOCK + "dtoverlay=dwc2\n")
    with pytest.raises(ValueError, match="Existing USB controller"):
        boot.configure(path)


@pytest.mark.parametrize(
    ("value", "applies"), [("0x12", True), ("18", True), ("0x18", False), ("bad", True)]
)
def test_board_type_filter(value, applies):
    conflict = boot.find_usb_overlay(f"[board-type={value}]\ndtoverlay=dwc2\n")
    assert bool(conflict) == applies
