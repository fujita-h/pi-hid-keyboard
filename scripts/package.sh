#!/bin/bash
# No Git metadata or Git executable required. Excludes credentials and live macros.
set -euo pipefail
SOURCE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
mkdir -p "$SOURCE/dist"
tar --exclude='__pycache__' --exclude='*.pyc' -czf "$SOURCE/dist/keybridge.tar.gz" \
    -C "$SOURCE" app data/macros.example.json scripts systemd tests \
    requirements.txt requirements-dev.txt pyproject.toml README.md LICENSE
echo "$SOURCE/dist/keybridge.tar.gz"

