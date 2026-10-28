"""Bounded key timings shared by macro validation and HID execution."""

import math
import random


class KeyTiming:
    def __init__(self, base_ms, max_multiplier=1.0):
        if not math.isfinite(base_ms) or not 0 <= base_ms <= 1000:
            raise ValueError("Key timing must be between 0 and 1000 ms")
        if not math.isfinite(max_multiplier) or max_multiplier < 1:
            raise ValueError("Key timing max multiplier must be finite and at least 1.0")
        maximum_ms = base_ms * max_multiplier
        if maximum_ms > 1000:
            raise ValueError("Key timing including max multiplier must not exceed 1000 ms")
        self.seconds = base_ms / 1000
        self.max_seconds = maximum_ms / 1000

    def sample(self):
        if self.seconds == self.max_seconds:
            return self.seconds
        return random.uniform(self.seconds, self.max_seconds)
