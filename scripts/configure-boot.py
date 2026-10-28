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


def configure(path: Path, *, dry_run=False):
    text = path.read_text(encoding="utf-8")
    if BEGIN in text or END in text:
        if text.count(BEGIN) != 1 or text.count(END) != 1 or BLOCK not in text:
            raise ValueError("Modified KeyBridge block; inspect config.txt manually")
        # Check other active overlays even when our managed block already exists.
        unmanaged = text.replace(BLOCK, "")
    else:
        unmanaged = text
    if re.search(r"^\s*dtoverlay\s*=\s*(dwc2|dwc-otg)(?:[,\s]|$)", unmanaged, re.M):
        raise ValueError("Existing USB controller overlay; remove/reconcile it manually first")
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
