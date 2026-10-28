#!/bin/bash
# Refresh APT metadata only when a required system package is missing.
set -euo pipefail

required_packages=(python3 python3-venv python3-pip kmod)
missing_packages=()
for package in "${required_packages[@]}"; do
    package_status=$(dpkg-query -W -f='${db:Status-Status}' "$package" 2>/dev/null) || package_status=""
    if [[ "$package_status" != installed ]]; then
        missing_packages+=("$package")
    fi
done

if [[ ${#missing_packages[@]} -eq 0 ]]; then
    echo "Required system packages are already installed; skipping APT update and install."
else
    echo "Installing missing system packages: ${missing_packages[*]}"
    apt-get update
    apt-get install -y "${missing_packages[@]}"
fi
