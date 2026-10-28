import pytest

from app.key_timing import KeyTiming


@pytest.mark.parametrize(("base", "multiplier"), [(20, 1.0), (0, 1.5)])
def test_fixed_or_zero_timing_needs_no_random_draw(base, multiplier, monkeypatch):
    def unexpected_draw(*_):
        pytest.fail("Fixed timings must not draw random numbers")

    monkeypatch.setattr("app.key_timing.random.uniform", unexpected_draw)
    timing = KeyTiming(base, multiplier)
    assert [timing.sample() for _ in range(3)] == [base / 1000] * 3


def test_timing_draws_each_time_between_base_and_upper_multiplier(monkeypatch):
    fractions = iter([0, 0.5, 1])

    def draw(lower, upper):
        assert lower == 0.02
        assert upper == 0.03
        return lower + (upper - lower) * next(fractions)

    monkeypatch.setattr("app.key_timing.random.uniform", draw)
    timing = KeyTiming(20, 1.5)
    assert [timing.sample() for _ in range(3)] == pytest.approx([0.02, 0.025, 0.03])


@pytest.mark.parametrize("base", [-1, 1001, float("nan"), float("inf"), -float("inf")])
def test_invalid_base_timing_rejected(base):
    with pytest.raises(ValueError):
        KeyTiming(base)


@pytest.mark.parametrize("multiplier", [-1, 0, 0.99, float("nan"), float("inf"), -float("inf")])
def test_invalid_multiplier_rejected(multiplier):
    with pytest.raises(ValueError, match="multiplier"):
        KeyTiming(20, multiplier)


def test_upper_timing_limit_includes_multiplier():
    assert KeyTiming(500, 2).max_seconds == 1
    with pytest.raises(ValueError, match="1000 ms"):
        KeyTiming(500, 2.01)
    with pytest.raises(ValueError, match="1000 ms"):
        KeyTiming(20, 1e308)
