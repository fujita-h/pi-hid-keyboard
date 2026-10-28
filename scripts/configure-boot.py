#!/usr/bin/env python3
"""Append a managed peripheral overlay; preserve the original boot configuration."""

import argparse
import os
import re
import shutil
import tempfile
from pathlib import Path

BEGIN = "# BEGIN KeyBridge"
END = "# END KeyBridge"
BLOCK = f"{BEGIN}\n[all]\ndtoverlay=dwc2,dr_mode=peripheral\n{END}\n"
OVERLAY = "dtoverlay=dwc2,dr_mode=peripheral"
# Model filters documented by Raspberry Pi. A Zero 2 W also reads pi0/pi0w.
# https://www.raspberrypi.com/documentation/computers/config_txt.html#conditional-filters
MODEL_FILTERS = {
    "pi1",
    "pi2",
    "pi3",
    "pi3+",
    "pi4",
    "pi5",
    "pi400",
    "pi500",
    "cm0",
    "cm1",
    "cm3",
    "cm3+",
    "cm4",
    "cm4s",
    "cm5",
    "pi0",
    "pi0w",
    "pi02",
}
ZERO2_FILTERS = {"pi0", "pi0w", "pi02"}


def find_usb_overlay(text):
    """Find an overlay that could apply to Zero 2 W; leave other models alone.

    Unknown GPIO, display, serial and other conditions remain potentially active.
    We only ignore an overlay when a known model filter excludes this board, or
    an explicit [none] disables settings. Model filters replace each other;
    [all] resets every condition. Included files still require manual review.
    """
    model_matches = True
    disabled = False
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        header = re.fullmatch(r"\[([^\]]+)\]", line)
        if header:
            condition = header[1].strip()
            if condition == "all":
                model_matches, disabled = True, False
            elif condition == "none":
                disabled = True
            elif condition in MODEL_FILTERS:
                model_matches = condition in ZERO2_FILTERS
            elif condition.startswith("board-type="):
                try:
                    model_matches = int(condition.partition("=")[2], 0) == 0x12
                except ValueError:
                    # An unrecognised model condition must not hide a conflict.
                    model_matches = True
            continue
        if (
            model_matches
            and not disabled
            and re.match(r"dtoverlay\s*=\s*(dwc2|dwc-otg)(?:[,\s]|$)", line)
        ):
            return number, line
    return None


def configure(path: Path, *, dry_run=False):
    text = path.read_text(encoding="utf-8")
    if BEGIN in text or END in text:
        if text.count(BEGIN) != 1 or text.count(END) != 1 or BLOCK not in text:
            raise ValueError("Modified KeyBridge block; inspect config.txt manually")
        # Keep the block's [all] reset and line numbers when checking other
        # overlays. Removing the entire block could hide conflicts after it.
        unmanaged = text.replace(BLOCK, BLOCK.replace(OVERLAY, "# Managed KeyBridge overlay"))
    else:
        unmanaged = text
    conflict = find_usb_overlay(unmanaged)
    if conflict:
        number, line = conflict
        raise ValueError(
            f"Existing USB controller overlay at line {number}: {line}; "
            "may apply to Zero 2 W, reconcile it manually first"
        )
    if BLOCK in text:
        return False
    if dry_run:
        print(f"Would back up {path} and append:\n{BLOCK}")
        return True
    backup = path.with_name(path.name + ".keybridge.bak")
    if not backup.exists():
        shutil.copy2(path, backup)
    fd, name = tempfile.mkstemp(prefix=".keybridge-boot-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(text.rstrip("\n") + "\n\n" + BLOCK)
            stream.flush()
            os.fsync(stream.fileno())
        shutil.copymode(path, name)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        changed = configure(args.path, dry_run=args.dry_run)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"KeyBridge boot setup: {exc}\n")
    if not args.dry_run:
        print(
            "USB overlay configured; reboot required."
            if changed
            else "USB overlay already configured."
        )


if __name__ == "__main__":
    main()
