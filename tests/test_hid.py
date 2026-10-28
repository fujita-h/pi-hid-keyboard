import errno
import os
import stat
from types import SimpleNamespace

import pytest

from app.hid_keyboard import RELEASE_REPORT, HIDError, HIDKeyboard, KeyMappingError, USLayout
from app.key_timing import KeyTiming
from app.macro_executor import MacroCompiler, MacroExecutor


@pytest.mark.parametrize(
    ("char", "modifier", "code"),
    [
        ("a", 0, 4),
        ("Z", 2, 29),
        ("1", 0, 0x1E),
        ("0", 0, 0x27),
        ("!", 2, 0x1E),
        ("@", 2, 0x1F),
        (")", 2, 0x27),
        ("\\", 0, 0x31),
        ("|", 2, 0x31),
        ("~", 2, 0x35),
        ("\n", 0, 0x28),
        ("\t", 0, 0x2B),
        (" ", 0, 0x2C),
    ],
)
def test_us_character_report(char, modifier, code):
    assert USLayout().character(char) == bytes([modifier, 0, code, 0, 0, 0, 0, 0])


def test_every_printable_ascii_is_supported():
    for codepoint in range(32, 127):
        assert len(USLayout().character(chr(codepoint))) == 8


@pytest.mark.parametrize("value", ["あ", "é", "\x00", "\x7f", "", "ab"])
def test_unsupported_text(value):
    with pytest.raises(KeyMappingError):
        USLayout().character(value)


def test_named_keys_modifiers_and_rollover():
    layout = USLayout()
    assert layout.key("DELETE")[2] == 0x4C
    assert layout.key("UP")[2] == 0x52
    assert layout.key("RWIN")[0] == 0x80
    assert layout.combo(["CTRL", "ALT", "DELETE"]) == bytes([5, 0, 0x4C, 0, 0, 0, 0, 0])
    assert layout.combo(["CTRL", "A"])[0:3] == bytes([1, 0, 4])
    assert layout.combo(["A", "B", "C", "D", "E", "F"])[2:] == bytes(range(4, 10))


@pytest.mark.parametrize(
    "keys",
    [
        ["A"],
        ["CTRL", "LCTRL"],
        ["a", "A"],
        ["NOPE", "A"],
        ["A", "B", "C", "D", "E", "F", "G"],
        ["CTRL", 1],
        "CTRL+A",
    ],
)
def test_bad_combos(keys):
    with pytest.raises(KeyMappingError):
        USLayout().combo(keys)


@pytest.fixture
def transport(monkeypatch):
    writes, opens, closes = [], [], []

    def open_device(*args):
        opens.append(args)
        return 17

    fake_os = SimpleNamespace(**{name: getattr(os, name) for name in dir(os)})
    fake_os.open = open_device
    fake_os.fstat = lambda fd: SimpleNamespace(st_mode=stat.S_IFCHR)
    fake_os.close = closes.append

    def write(fd, report):
        writes.append(report)
        return len(report)

    fake_os.write = write
    monkeypatch.setattr("app.hid_keyboard.os", fake_os)
    keyboard = HIDKeyboard(sleep=lambda _: None)
    return keyboard, writes, opens, closes


def test_press_and_release_and_reopen(transport):
    keyboard, writes, opens, closes = transport
    report = USLayout().key("ENTER")
    for _ in range(2):
        with keyboard.session():
            keyboard.tap(report)
    assert writes == [RELEASE_REPORT, report, RELEASE_REPORT, RELEASE_REPORT] * 2
    assert len(opens) == 2 and closes == [17, 17]
    assert opens[0][1] & os.O_NONBLOCK


@pytest.mark.parametrize(
    ("hold_multiplier", "interval_multiplier"), [(1, 1), (1.5, 1), (1, 2), (1.5, 2)]
)
def test_each_key_samples_hold_and_interval_independently(
    transport, monkeypatch, hold_multiplier, interval_multiplier
):
    keyboard, writes, _, _ = transport
    keyboard.hold_timing = KeyTiming(20, hold_multiplier)
    sleeps = []
    keyboard.sleep = sleeps.append
    draws = {}

    def draw(lower, upper):
        count = draws.get((lower, upper), 0)
        draws[(lower, upper)] = count + 1
        return lower + (upper - lower) * (count % 3) / 2

    monkeypatch.setattr("app.key_timing.random.uniform", draw)
    compiler = MacroCompiler(
        hold_ms=20,
        interval_ms=30,
        hold_max_multiplier=hold_multiplier,
        interval_max_multiplier=interval_multiplier,
    )
    executor = MacroExecutor(keyboard, compiler, sleep=sleeps.append)
    executor.execute(
        [
            {"type": "text", "value": "aa"},
            {"type": "combo", "keys": ["CTRL", "A"]},
            {"type": "delay", "ms": 300},
            {"type": "key", "value": "ENTER"},
        ]
    )
    expected = []
    for fraction in (0, 0.5, 1, 0):
        expected.extend(
            [
                0.02 * (1 + (hold_multiplier - 1) * fraction),
                0.03 * (1 + (interval_multiplier - 1) * fraction),
            ]
        )
    expected.insert(6, 0.3)
    assert sleeps == pytest.approx(expected)
    assert len(draws) == (hold_multiplier > 1) + (interval_multiplier > 1)
    assert all(count == 4 for count in draws.values())
    layout = USLayout()
    reports = [layout.key("a"), layout.key("a"), layout.combo(["CTRL", "A"]), layout.key("ENTER")]
    assert writes == [
        RELEASE_REPORT,
        *(r for report in reports for r in (report, RELEASE_REPORT)),
        RELEASE_REPORT,
    ]


def test_release_on_execution_exception(transport):
    keyboard, writes, _, closes = transport
    with pytest.raises(RuntimeError, match="failure"):
        with keyboard.session():
            keyboard.tap(USLayout().key("A"))
            raise RuntimeError("failure")
    assert writes[-1] == RELEASE_REPORT
    assert closes == [17]


def test_disconnect_attempts_release_then_reconnects(transport, monkeypatch):
    keyboard, writes, _, closes = transport
    attempts = []

    def flaky_write(fd, report):
        attempts.append(report)
        if len(attempts) in (2, 3, 4):
            raise OSError(errno.ESHUTDOWN, "USB disconnected")
        writes.append(report)
        return 8

    monkeypatch.setattr("app.hid_keyboard.os.write", flaky_write)
    with pytest.raises(HIDError):
        with keyboard.session():
            keyboard.tap(USLayout().key("A"))
    assert attempts[2:] == [RELEASE_REPORT, RELEASE_REPORT]
    with keyboard.session():
        keyboard.tap(USLayout().key("B"))
    assert writes[-2:] == [RELEASE_REPORT, RELEASE_REPORT]
    assert closes == [17, 17]


def test_would_block_has_bounded_timeout(transport, monkeypatch):
    keyboard, _, _, closes = transport
    keyboard.write_timeout = 0

    def blocked(*args):
        raise BlockingIOError(errno.EAGAIN, "busy")

    monkeypatch.setattr("app.hid_keyboard.os.write", blocked)
    with pytest.raises(HIDError, match="timeout"), keyboard.session():
        pass
    assert closes == [17]


def test_retry_on_eagain(transport, monkeypatch):
    keyboard, writes, _, _ = transport

    def interrupted(fd, report):
        monkeypatch.setattr(
            "app.hid_keyboard.os.write", lambda fd, report: writes.append(report) or 8
        )
        raise BlockingIOError(errno.EAGAIN, "try again")

    monkeypatch.setattr("app.hid_keyboard.os.write", interrupted)
    with keyboard.session():
        keyboard.tap(USLayout().key("A"))
    assert writes[-1] == RELEASE_REPORT


def test_short_report_write_fails_and_attempts_release(transport, monkeypatch):
    keyboard, writes, _, closes = transport

    def short_write(fd, report):
        writes.append(report)
        return 4 if len(writes) == 2 else 8

    monkeypatch.setattr("app.hid_keyboard.os.write", short_write)
    with pytest.raises(HIDError, match="Incomplete"), keyboard.session():
        keyboard.tap(USLayout().key("A"))
    assert writes[-1] == RELEASE_REPORT
    assert closes == [17]


def test_missing_device_and_regular_file_are_rejected(tmp_path):
    keyboard = HIDKeyboard(tmp_path / "missing")
    with pytest.raises(HIDError, match="Cannot open"), keyboard.session():
        pass
    regular = tmp_path / "regular"
    regular.write_bytes(b"do not modify")
    with pytest.raises(HIDError, match="character device"), HIDKeyboard(regular).session():
        pass
    assert regular.read_bytes() == b"do not modify"


def test_status_separates_node_from_connection(tmp_path):
    root = tmp_path / "udc"
    (root / "controller").mkdir(parents=True)
    state = root / "controller" / "state"
    state.write_text("not attached\n")
    keyboard = HIDKeyboard("/dev/null", udc_root=root)
    assert keyboard.status()["device_exists"] is True
    assert keyboard.status()["connected"] is False
    assert keyboard.status()["ready"] is False
    state.write_text("configured\n")
    assert keyboard.status()["ready"] is True
    assert (
        HIDKeyboard(tmp_path / "missing", udc_root=tmp_path / "none").status()["connected"] is None
    )
