#!/bin/bash
# Install from an SCP-uploaded folder, an extracted archive, or a Git checkout.
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "Run: sudo bash scripts/install.sh" >&2; exit 1; }
SOURCE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
INSTALL_DIR=/opt/keybridge
ENV_FILE=/etc/keybridge/keybridge.env

[[ -r /proc/device-tree/model ]] || { echo "This installer requires a Raspberry Pi." >&2; exit 1; }
model=$(tr -d '\0' < /proc/device-tree/model)
[[ "$model" == *"Raspberry Pi Zero 2 W"* ]] || { echo "Supported target: Raspberry Pi Zero 2 W. Found: $model" >&2; exit 1; }
if [[ -f /boot/firmware/config.txt ]]; then
    BOOT_CONFIG=/boot/firmware/config.txt
elif [[ -f /boot/config.txt ]]; then
    BOOT_CONFIG=/boot/config.txt
else
    echo "Cannot find Raspberry Pi config.txt." >&2
    exit 1
fi

echo "KeyBridge will install Python packages, /opt/keybridge, /etc/keybridge,"
echo "two systemd units, a device permission rule, and a dwc2 modules-load file."
echo "It appends a managed block to $BOOT_CONFIG and keeps config.txt.keybridge.bak."
echo "Existing macros and credentials are preserved. Network and SSH settings are unchanged."
python3 "$SOURCE/scripts/configure-boot.py" "$BOOT_CONFIG" --dry-run
apt-get update
apt-get install -y python3 python3-venv python3-pip kmod

if ! getent group keybridge >/dev/null; then
    groupadd --system keybridge
fi
if ! id keybridge >/dev/null 2>&1; then
    useradd --system --gid keybridge --home-dir "$INSTALL_DIR" --no-create-home --shell /usr/sbin/nologin keybridge
fi
# Do not update code underneath a running interpreter.
systemctl stop keybridge-web.service 2>/dev/null || true
install -d -m 0755 "$INSTALL_DIR" "$INSTALL_DIR/app" "$INSTALL_DIR/scripts" "$INSTALL_DIR/systemd"
install -d -o keybridge -g keybridge -m 0700 "$INSTALL_DIR/data"
install -d -m 0700 /etc/keybridge
if [[ "$SOURCE" != "$INSTALL_DIR" ]]; then
    for directory in app scripts systemd; do
        cp -a "$SOURCE/$directory/." "$INSTALL_DIR/$directory/"
        chown -R root:root "$INSTALL_DIR/$directory"
        chmod -R go-w "$INSTALL_DIR/$directory"
    done
    install -m 0644 "$SOURCE/requirements.txt" "$INSTALL_DIR/requirements.txt"
    install -m 0644 "$SOURCE/README.md" "$INSTALL_DIR/README.md"
    install -m 0644 "$SOURCE/data/macros.example.json" "$INSTALL_DIR/data/macros.example.json"
fi
# Never copy a development data/macros.json over the live configuration.
chmod 0755 "$INSTALL_DIR/scripts/"*.sh
python3 -m venv "$INSTALL_DIR/.venv"
"$INSTALL_DIR/.venv/bin/python" -m pip install -r "$INSTALL_DIR/requirements.txt"
if [[ ! -f "$ENV_FILE" ]]; then
    "$INSTALL_DIR/.venv/bin/python" "$INSTALL_DIR/scripts/configure-auth.py" --output "$ENV_FILE"
fi
chown root:root "$ENV_FILE"
chmod 0600 "$ENV_FILE"

python3 "$INSTALL_DIR/scripts/configure-boot.py" "$BOOT_CONFIG"
printf 'dwc2\nlibcomposite\n' > /etc/modules-load.d/keybridge.conf
# USB unplug/replug normally leaves the node intact; udev also covers recreation.
printf '%s\n' 'SUBSYSTEM=="hidg", KERNEL=="hidg0", GROUP="keybridge", MODE="0660"' > /etc/udev/rules.d/99-keybridge-hid.rules
udevadm control --reload-rules
install -m 0644 "$INSTALL_DIR/systemd/"*.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable keybridge-gadget.service keybridge-web.service
echo "Installation complete. Reboot with: sudo reboot"
echo "Then open http://<Pi-IP>:8000 from another device on the same trusted LAN."

