#!/bin/bash
# ConfigFS boot-protocol keyboard. Only manages the gadget named keybridge.
set -euo pipefail

GADGET=/sys/kernel/config/usb_gadget/keybridge
HID_GROUP=keybridge

die() { echo "KeyBridge: $*" >&2; exit 1; }
[[ $EUID -eq 0 ]] || die "Run as root (systemd normally handles this)."

stop_gadget() {
    [[ -d "$GADGET" ]] || return 0
    if [[ -n $(cat "$GADGET/UDC") ]]; then
        printf '\n' > "$GADGET/UDC"
    fi
    [[ ! -L "$GADGET/configs/c.1/hid.usb0" ]] || rm "$GADGET/configs/c.1/hid.usb0"
    [[ ! -d "$GADGET/configs/c.1/strings/0x409" ]] || rmdir "$GADGET/configs/c.1/strings/0x409"
    [[ ! -d "$GADGET/configs/c.1" ]] || rmdir "$GADGET/configs/c.1"
    [[ ! -d "$GADGET/functions/hid.usb0" ]] || rmdir "$GADGET/functions/hid.usb0"
    [[ ! -d "$GADGET/strings/0x409" ]] || rmdir "$GADGET/strings/0x409"
    rmdir "$GADGET"
}

case "${1:-start}" in
    stop) stop_gadget; exit 0 ;;
    start) ;;
    *) die "Usage: $0 [start|stop]" ;;
esac

getent group "$HID_GROUP" >/dev/null || die "Install first: missing keybridge group."
modprobe libcomposite
if ! mountpoint -q /sys/kernel/config; then
    mount -t configfs none /sys/kernel/config
fi

# Rebuild our own gadget on a service restart, including after partial setup.
stop_gadget
udc="${KEYBRIDGE_UDC:-}"
for _ in {1..50}; do
    if [[ -n "$udc" ]]; then
        [[ -d "/sys/class/udc/$udc" ]] && break
    else
        shopt -s nullglob
        controllers=(/sys/class/udc/*)
        shopt -u nullglob
        if [[ ${#controllers[@]} -eq 1 ]]; then
            udc=${controllers[0]##*/}
            break
        elif [[ ${#controllers[@]} -gt 1 ]]; then
            die "Multiple UDCs; set KEYBRIDGE_UDC in the gadget service environment."
        fi
    fi
    sleep 0.2
done
[[ -n "$udc" && -d "/sys/class/udc/$udc" ]] || die "No UDC. Enable dwc2 peripheral mode and reboot."

mkdir -p "$GADGET"
# Prototype IDs commonly used in Linux gadget examples; replace with allocated
# VID/PID before distributing a product. These do not confer USB-IF certification.
printf '0x1d6b\n' > "$GADGET/idVendor"
printf '0x0104\n' > "$GADGET/idProduct"
printf '0x0100\n' > "$GADGET/bcdDevice"
printf '0x0200\n' > "$GADGET/bcdUSB"
mkdir -p "$GADGET/strings/0x409"
serial=$(cat /etc/machine-id)
printf '%s\n' "$serial" > "$GADGET/strings/0x409/serialnumber"
printf 'KeyBridge\n' > "$GADGET/strings/0x409/manufacturer"
printf 'KeyBridge USB Keyboard\n' > "$GADGET/strings/0x409/product"
mkdir -p "$GADGET/configs/c.1/strings/0x409"
printf 'HID Keyboard\n' > "$GADGET/configs/c.1/strings/0x409/configuration"
printf '0x80\n' > "$GADGET/configs/c.1/bmAttributes"
printf '250\n' > "$GADGET/configs/c.1/MaxPower"
mkdir -p "$GADGET/functions/hid.usb0"
printf '1\n' > "$GADGET/functions/hid.usb0/protocol"
printf '1\n' > "$GADGET/functions/hid.usb0/subclass"
printf '8\n' > "$GADGET/functions/hid.usb0/report_length"
printf '%b' '\x05\x01\x09\x06\xa1\x01\x05\x07\x19\xe0\x29\xe7\x15\x00\x25\x01\x75\x01\x95\x08\x81\x02\x95\x01\x75\x08\x81\x03\x95\x05\x75\x01\x05\x08\x19\x01\x29\x05\x91\x02\x95\x01\x75\x03\x91\x03\x95\x06\x75\x08\x15\x00\x25\x65\x05\x07\x19\x00\x29\x65\x81\x00\xc0' > "$GADGET/functions/hid.usb0/report_desc"
ln -s "$GADGET/functions/hid.usb0" "$GADGET/configs/c.1/hid.usb0"
printf '%s\n' "$udc" > "$GADGET/UDC"

# Do not accidentally give the web service access to another gadget's device.
device_numbers=$(cat "$GADGET/functions/hid.usb0/dev")
for _ in {1..50}; do
    if [[ -c /dev/hidg0 ]]; then
        actual_numbers=$(stat -c '%t:%T' /dev/hidg0)
        IFS=: read -r major minor <<< "$device_numbers"
        printf -v expected_numbers '%x:%x' "$major" "$minor"
        [[ "$actual_numbers" == "$expected_numbers" ]] || die "hidg0 belongs to another gadget."
        chown root:"$HID_GROUP" /dev/hidg0
        chmod 0660 /dev/hidg0
        echo "KeyBridge HID keyboard ready on /dev/hidg0 ($udc)."
        exit 0
    fi
    sleep 0.1
done
die "Gadget bound, but /dev/hidg0 did not appear."

