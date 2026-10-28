import threading

import pytest

from app.hid_keyboard import USLayout
from app.macro_executor import BusyError, MacroCompiler, MacroExecutor, ValidationError


def test_exact_sequence_and_delays(keyboard):
    sleeps = []
    executor = MacroExecutor(keyboard, MacroCompiler(), sleep=sleeps.append)
    executor.execute(
        [
            {"type": "text", "value": "Hi!\r\n"},
            {"type": "combo", "keys": ["CTRL", "A"]},
            {"type": "delay", "ms": 300},
            {"type": "key", "value": "TAB"},
        ]
    )
    layout = USLayout()
    assert keyboard.reports == [
        *(layout.character(c) for c in "Hi!\n"),
        layout.combo(["CTRL", "A"]),
        layout.key("TAB"),
    ]
    assert sleeps == [0.02] * 5 + [0.3, 0.02]


@pytest.mark.parametrize(
    "steps",
    [
        [],
        None,
        [{"type": "unknown"}],
        [{"type": "text", "value": "日本語"}],
        [{"type": "delay", "ms": True}],
        [{"type": "delay", "ms": -1}],
        [{"type": "delay", "ms": 1.5}],
        [{"type": "delay", "ms": 60001}],
        [{"type": "delay", "ms": 60000}, {"type": "key", "value": "A"}],
        [{"type": "key", "value": "A", "extra": "ignored?"}],
        [{"type": "text", "value": "a" * 10001}],
    ],
)
def test_invalid_steps(steps):
    with pytest.raises(ValidationError):
        MacroCompiler().compile(steps)


def test_invalid_later_step_cannot_cause_partial_typing(keyboard):
    executor = MacroExecutor(keyboard, MacroCompiler())
    with pytest.raises(ValidationError):
        executor.execute([{"type": "text", "value": "good"}, {"type": "text", "value": "悪い"}])
    assert keyboard.sessions == 0
    assert not executor.busy


def test_parallel_execution_is_rejected_and_lock_recovers(keyboard):
    entered = threading.Event()
    release = threading.Event()
    failures = []

    def pause(_):
        entered.set()
        assert release.wait(3)

    executor = MacroExecutor(keyboard, MacroCompiler(), sleep=pause)

    def execute():
        try:
            executor.execute([{"type": "key", "value": "A"}])
        except BaseException as exc:
            failures.append(exc)

    thread = threading.Thread(target=execute)
    thread.start()
    try:
        assert entered.wait(3)
        assert executor.busy
        with pytest.raises(BusyError):
            executor.execute([{"type": "key", "value": "B"}])
    finally:
        release.set()
        thread.join(3)
    assert not failures
    assert not executor.busy
    assert keyboard.reports == [USLayout().key("A")]


def test_exception_frees_execution_lock(keyboard):
    def fail(_):
        raise RuntimeError("test failure")

    executor = MacroExecutor(keyboard, MacroCompiler(), sleep=fail)
    with pytest.raises(RuntimeError):
        executor.execute([{"type": "key", "value": "A"}])
    assert not executor.busy
    executor.sleep = lambda _: None
    executor.execute([{"type": "key", "value": "B"}])


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1, 1001])
def test_invalid_timing(value):
    with pytest.raises(ValueError):
        MacroCompiler(interval_ms=value)


@pytest.mark.parametrize(
    "step",
    [
        {"type": "text", "value": "a"},
        {"type": "key", "value": "ENTER"},
        {"type": "combo", "keys": ["CTRL", "A"]},
    ],
)
def test_random_timing_maximum_validated_before_any_typing(keyboard, step):
    steps = [{"type": "delay", "ms": 59950}, step]
    assert MacroCompiler().compile(steps)
    compiler = MacroCompiler(interval_max_multiplier=1.5, hold_max_multiplier=2)
    executor = MacroExecutor(keyboard, compiler)
    with pytest.raises(ValidationError, match="60 seconds"):
        executor.execute(steps)
    assert keyboard.sessions == 0
    assert keyboard.reports == []


def test_random_timing_duration_at_limit_and_above():
    compiler = MacroCompiler(
        interval_ms=100, hold_ms=100, interval_max_multiplier=3, hold_max_multiplier=2
    )
    assert compiler.compile([{"type": "text", "value": "a" * 120}])
    with pytest.raises(ValidationError, match="60 seconds"):
        compiler.compile([{"type": "text", "value": "a" * 121}])
