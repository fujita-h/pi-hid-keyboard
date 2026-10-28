"""US-layout report generation and bounded, reconnectable Linux HID transport.

Report generation has no hardware dependencies. Each session opens the device
again, so a failed/disconnected session cannot leave a stale descriptor in use.
"""

import contextlib
import errno
import logging
import os
import stat
import time
from pathlib import Path

log = logging.getLogger(__name__)
RELEASE_REPORT = bytes(8)


class KeyMappingError(ValueError):
    pass


class HIDError(RuntimeError):
    pass


class USLayout:
    """Mapping boundary for future layouts; key names are physical US keys."""

    name = "US"
    modifiers = {
        "CTRL": 0x01,
        "LCTRL": 0x01,
        "SHIFT": 0x02,
        "LSHIFT": 0x02,
        "ALT": 0x04,
        "LALT": 0x04,
        "WIN": 0x08,
        "WINDOWS": 0x08,
        "GUI": 0x08,
        "LWIN": 0x08,
        "RCTRL": 0x10,
        "RSHIFT": 0x20,
        "RALT": 0x40,
        "RWIN": 0x80,
    }
    keys = {
        "ENTER": 0x28,
        "ESC": 0x29,
        "ESCAPE": 0x29,
        "BACKSPACE": 0x2A,
        "TAB": 0x2B,
        "SPACE": 0x2C,
        "CAPSLOCK": 0x39,
        "PRINTSCREEN": 0x46,
        "SCROLLLOCK": 0x47,
        "PAUSE": 0x48,
        "INSERT": 0x49,
        "HOME": 0x4A,
        "PAGEUP": 0x4B,
        "DELETE": 0x4C,
        "END": 0x4D,
        "PAGEDOWN": 0x4E,
        "RIGHT": 0x4F,
        "LEFT": 0x50,
        "DOWN": 0x51,
        "UP": 0x52,
        **{f"F{i}": 0x39 + i for i in range(1, 13)},
    }
    # unshifted / shifted pairs, with HID Keyboard/Keypad usage IDs
    punctuation = {
        "-": (0, 0x2D),
        "_": (2, 0x2D),
        "=": (0, 0x2E),
        "+": (2, 0x2E),
        "[": (0, 0x2F),
        "{": (2, 0x2F),
        "]": (0, 0x30),
        "}": (2, 0x30),
        "\\": (0, 0x31),
        "|": (2, 0x31),
        ";": (0, 0x33),
        ":": (2, 0x33),
        "'": (0, 0x34),
        '"': (2, 0x34),
        "`": (0, 0x35),
        "~": (2, 0x35),
        ",": (0, 0x36),
        "<": (2, 0x36),
        ".": (0, 0x37),
        ">": (2, 0x37),
        "/": (0, 0x38),
        "?": (2, 0x38),
        " ": (0, 0x2C),
        "\n": (0, 0x28),
        "\r": (0, 0x28),
        "\t": (0, 0x2B),
        **{c: (2, 0x1E + i) for i, c in enumerate("!@#$%^&*()")},
    }

    def character(self, char: str) -> bytes:
        if len(char) != 1:
            raise KeyMappingError("Expected one character")
        if "a" <= char <= "z":
            modifier, code = 0, ord(char) - ord("a") + 4
        elif "A" <= char <= "Z":
            modifier, code = 2, ord(char) - ord("A") + 4
        elif char in "1234567890":
            modifier, code = 0, "1234567890".index(char) + 0x1E
        elif char in self.punctuation:
            modifier, code = self.punctuation[char]
        else:
            raise KeyMappingError(f"Unsupported US ASCII character: U+{ord(char):04X}")
        return bytes([modifier, 0, code, 0, 0, 0, 0, 0])

    def key(self, name: str) -> bytes:
        if not isinstance(name, str) or not name:
            raise KeyMappingError("Key name must be a nonempty string")
        normalized = name.upper()
        if normalized in self.modifiers:
            return bytes([self.modifiers[normalized], 0, 0, 0, 0, 0, 0, 0])
        if normalized in self.keys:
            return bytes([0, 0, self.keys[normalized], 0, 0, 0, 0, 0])
        if len(name) == 1:
            # CTRL+A means the physical A key, without an implied Shift.
            return self.character(name.lower())
        raise KeyMappingError(f"Unknown key: {name}")

    def combo(self, names: list[str]) -> bytes:
        if not isinstance(names, list) or not 2 <= len(names) <= 14:
            raise KeyMappingError("A combo needs 2–14 key names (at most 6 ordinary keys)")
        modifier = 0
        codes = []
        explicit_modifiers = 0
        for name in names:
            report = self.key(name)
            if not report[2]:
                if explicit_modifiers & report[0]:
                    raise KeyMappingError("Duplicate modifier in combo")
                explicit_modifiers |= report[0]
            modifier |= report[0]
            if report[2]:
                if report[2] in codes:
                    raise KeyMappingError("Duplicate physical key in combo")
                codes.append(report[2])
        if len(codes) > 6:
            raise KeyMappingError("A HID report supports at most 6 ordinary keys")
        return bytes([modifier, 0, *codes, *([0] * (6 - len(codes)))])


class HIDKeyboard:
    def __init__(
        self,
        device="/dev/hidg0",
        *,
        hold_ms=20,
        write_timeout=1.0,
        udc_root="/sys/class/udc",
        sleep=time.sleep,
    ):
        self.device = Path(device)
        self.hold_seconds = hold_ms / 1000
        self.write_timeout = write_timeout
        self.udc_root = Path(udc_root)
        self.sleep = sleep
        self._fd = None

    def status(self):
        """Device existence is distinct from host enumeration; neither proves delivery."""
        try:
            exists = stat.S_ISCHR(self.device.stat().st_mode)
            writable = exists and os.access(self.device, os.W_OK)
        except OSError:
            exists = writable = False
        states = {}
        try:
            for path in self.udc_root.glob("*/state"):
                try:
                    states[path.parent.name] = path.read_text().strip()
                except OSError:
                    continue
        except OSError:
            pass
        connected = any(s == "configured" for s in states.values()) if states else None
        return {
            "device_exists": exists,
            "writable": writable,
            "connected": connected,
            "udc_states": states,
            "ready": writable and connected is not False,
        }

    def _write(self, report):
        if self._fd is None:
            raise HIDError("HID session is not open")
        deadline = time.monotonic() + self.write_timeout
        while True:
            try:
                if os.write(self._fd, report) != 8:
                    raise HIDError("Incomplete HID report write")
                return
            except OSError as exc:
                if exc.errno in (errno.EAGAIN, errno.EWOULDBLOCK, errno.EINTR):
                    if time.monotonic() < deadline:
                        self.sleep(0.005)
                        continue
                    raise HIDError("USB host did not accept a HID report (timeout)") from exc
                raise HIDError("HID write failed; check the USB data connection") from exc

    def _release_after_error(self):
        try:
            self._write(RELEASE_REPORT)
        except (HIDError, OSError):
            log.warning("Could not release keys after a HID error")

    @contextlib.contextmanager
    def session(self):
        try:
            self._fd = os.open(self.device, os.O_WRONLY | os.O_NONBLOCK | os.O_CLOEXEC)
        except OSError as exc:
            raise HIDError("Cannot open HID device; check gadget setup and permissions") from exc
        try:
            if not stat.S_ISCHR(os.fstat(self._fd).st_mode):
                raise HIDError("HID path is not a character device")
            self._write(RELEASE_REPORT)
            try:
                yield self
            except BaseException:
                self._release_after_error()
                raise
            else:
                self._write(RELEASE_REPORT)
        finally:
            os.close(self._fd)
            self._fd = None

    def tap(self, report):
        try:
            self._write(report)
            self.sleep(self.hold_seconds)
        except BaseException:
            self._release_after_error()
            raise
        else:
            self._write(RELEASE_REPORT)
