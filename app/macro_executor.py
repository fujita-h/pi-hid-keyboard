"""Validate/compile a whole macro before sending its first keystroke."""

import threading
import time
from dataclasses import dataclass

from app.hid_keyboard import KeyMappingError, USLayout
from app.key_timing import KeyTiming


class ValidationError(ValueError):
    pass


class BusyError(RuntimeError):
    pass


@dataclass(frozen=True)
class Operation:
    report: bytes | None = None
    delay: float = 0


class MacroCompiler:
    MAX_SECONDS = 60

    def __init__(
        self,
        layout=None,
        *,
        interval_ms=20,
        hold_ms=20,
        interval_max_multiplier=1.0,
        hold_max_multiplier=1.0,
    ):
        self.layout = layout or USLayout()
        self.interval_timing = KeyTiming(interval_ms, interval_max_multiplier)
        self.hold_timing = KeyTiming(hold_ms, hold_max_multiplier)

    def compile(self, steps):
        if not isinstance(steps, list) or not 1 <= len(steps) <= 500:
            raise ValidationError("steps must contain 1–500 operations")
        result = []
        duration = 0
        max_key_seconds = self.interval_timing.max_seconds + self.hold_timing.max_seconds
        for index, step in enumerate(steps):
            try:
                if not isinstance(step, dict):
                    raise ValidationError("Step must be an object")
                kind = step.get("type")
                if kind in ("text", "key"):
                    if set(step) != {"type", "value"} or not isinstance(step["value"], str):
                        raise ValidationError("text/key requires only type and string value")
                    if kind == "text":
                        value = step["value"]
                        if len(value) > 10000:
                            raise ValidationError("Text is limited to 10000 characters")
                        # Treat CRLF as one Enter, rather than two.
                        reports = [self.layout.character(c) for c in value.replace("\r\n", "\n")]
                    else:
                        reports = [self.layout.key(step["value"])]
                    result.extend(Operation(report=r) for r in reports)
                    duration += len(reports) * max_key_seconds
                elif kind == "combo":
                    if set(step) != {"type", "keys"}:
                        raise ValidationError("combo requires only type and keys")
                    result.append(Operation(report=self.layout.combo(step["keys"])))
                    duration += max_key_seconds
                elif kind == "delay":
                    if (
                        set(step) != {"type", "ms"}
                        or type(step["ms"]) is not int
                        or not 0 <= step["ms"] <= 60000
                    ):
                        raise ValidationError("delay ms must be an integer between 0 and 60000")
                    result.append(Operation(delay=step["ms"] / 1000))
                    duration += step["ms"] / 1000
                else:
                    raise ValidationError("Unknown operation type")
                if duration > self.MAX_SECONDS or len(result) > 10000:
                    raise ValidationError("Macro exceeds 60 seconds or 10000 key operations")
            except (ValidationError, KeyMappingError) as exc:
                raise ValidationError(f"steps[{index}]: {exc}") from exc
        return tuple(result)


class MacroExecutor:
    def __init__(self, keyboard, compiler, *, sleep=time.sleep):
        self.keyboard = keyboard
        self.compiler = compiler
        self.sleep = sleep
        self._lock = threading.Lock()

    @property
    def busy(self):
        return self._lock.locked()

    def execute(self, steps):
        operations = self.compiler.compile(steps)
        if not self._lock.acquire(blocking=False):
            raise BusyError("Another macro is running; wait for it to finish")
        try:
            with self.keyboard.session():
                for op in operations:
                    if op.report is not None:
                        self.keyboard.tap(op.report)
                        self.sleep(self.compiler.interval_timing.sample())
                    else:
                        self.sleep(op.delay)
        finally:
            self._lock.release()
