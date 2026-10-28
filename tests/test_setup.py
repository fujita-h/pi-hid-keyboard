import importlib.util
import json
import os
import subprocess
import sys
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


@pytest.fixture
def run_package_installer(tmp_path):
    commands = tmp_path / "bin"
    commands.mkdir()
    query = commands / "dpkg-query"
    query.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "state = json.loads(os.environ['PACKAGE_TEST_STATES']).get(sys.argv[-1], 'installed')\n"
        "if state is None:\n"
        "    sys.exit(1)\n"
        "print(state, end='')\n"
    )
    apt = commands / "apt-get"
    apt.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "with open(os.environ['PACKAGE_TEST_LOG'], 'a') as stream:\n"
        "    stream.write(json.dumps(sys.argv[1:]) + '\\n')\n"
        "sys.exit(42 if sys.argv[1] == os.environ['PACKAGE_TEST_FAIL'] else 0)\n"
    )
    query.chmod(0o755)
    apt.chmod(0o755)
    log = tmp_path / "apt.jsonl"

    def run(states, *, fail=""):
        result = subprocess.run(
            ["bash", str(Path(__file__).resolve().parents[1] / "scripts/install-packages.sh")],
            env={
                **os.environ,
                "PATH": str(commands) + os.pathsep + os.environ["PATH"],
                "PACKAGE_TEST_STATES": json.dumps(states),
                "PACKAGE_TEST_LOG": str(log),
                "PACKAGE_TEST_FAIL": fail,
            },
            capture_output=True,
            text=True,
            timeout=10,
        )
        calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
        return result, calls

    return run


def test_installed_system_packages_skip_all_apt_access(run_package_installer):
    result, calls = run_package_installer({})
    assert result.returncode == 0, result.stderr
    assert calls == []
    assert "skipping APT update and install" in result.stdout


@pytest.mark.parametrize(
    "state", [None, "not-installed", "config-files", "unpacked", "half-configured"]
)
def test_only_missing_or_incomplete_system_packages_are_installed(run_package_installer, state):
    result, calls = run_package_installer({"python3-venv": state, "kmod": None})
    assert result.returncode == 0, result.stderr
    assert calls == [["update"], ["install", "-y", "python3-venv", "kmod"]]


def test_first_install_fetches_all_required_system_packages(run_package_installer):
    packages = ["python3", "python3-venv", "python3-pip", "kmod"]
    result, calls = run_package_installer(dict.fromkeys(packages))
    assert result.returncode == 0, result.stderr
    assert calls == [["update"], ["install", "-y", *packages]]


@pytest.mark.parametrize("fail", ["update", "install"])
def test_apt_failures_stop_package_installation(run_package_installer, fail):
    result, calls = run_package_installer({"python3-pip": None}, fail=fail)
    assert result.returncode == 42
    assert calls == (
        [["update"]] if fail == "update" else [["update"], ["install", "-y", "python3-pip"]]
    )
