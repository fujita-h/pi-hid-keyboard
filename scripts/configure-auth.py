#!/usr/bin/env python3
"""Create a mode-0600 environment file without exposing passwords in argv/logs."""

import argparse
import getpass
import os
import re
import secrets
import tempfile
from pathlib import Path

from werkzeug.security import generate_password_hash


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(".env"))
    args = parser.parse_args()
    username = input("Web username [keybridge]: ").strip() or "keybridge"
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", username):
        parser.error("Username must be 1–64 ASCII letters, digits, _, . or -")
    password = getpass.getpass("Web password (12+ characters): ")
    if len(password) < 12 or any(ord(c) < 32 for c in password):
        parser.error("Use at least 12 characters without control characters")
    if password != getpass.getpass("Confirm password: "):
        parser.error("Passwords do not match")
    password_hash = generate_password_hash(password, method="pbkdf2:sha256:600000")
    content = (
        f"KEYBRIDGE_USERNAME='{username}'\n"
        f"KEYBRIDGE_PASSWORD_HASH='{password_hash}'\n"
        f"KEYBRIDGE_SECRET_KEY='{secrets.token_hex(32)}'\n"
        "KEYBRIDGE_KEY_INTERVAL_MS=20\n"
        "KEYBRIDGE_KEY_HOLD_MS=20\n"
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".keybridge-auth-", dir=args.output.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, args.output)
    finally:
        if os.path.exists(name):
            os.unlink(name)
    print(f"Credentials saved to {args.output}. Restart KeyBridge after changing credentials.")


if __name__ == "__main__":
    main()
