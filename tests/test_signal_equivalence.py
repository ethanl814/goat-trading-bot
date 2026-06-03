# tests/test_signal_equivalence.py
"""The incremental-vs-naive guarantee (design principle 2).

RollingMeanStd updates mean/variance in O(1) via running sum/sum-of-squares over
a sliding window. This proves it matches a from-scratch recompute of the same
window at every step — i.e. the O(1) shortcut is correct, not just fast.
"""
import random
import statistics

import pytest

from bot.framework.state import RollingMeanStd


def _naive(window_vals):
    n = len(window_vals)
    mean = sum(window_vals) / n
    var = statistics.variance(window_vals) if n >= 2 else 0.0
    return mean, var


def test_incremental_matches_naive_over_random_stream():
    rng = random.Random(42)
    window = 20
    inc = RollingMeanStd(window)
    history: list[float] = []

    for _ in range(1000):
        x = rng.gauss(0.001, 0.02)
        inc.push(x)
        history.append(x)
        win = history[-window:]
        exp_mean, exp_var = _naive(win)
        assert inc.mean() == pytest.approx(exp_mean, abs=1e-9)
        assert inc.var() == pytest.approx(exp_var, abs=1e-9)
        assert inc.std() == pytest.approx(exp_var ** 0.5, abs=1e-9)


def test_ready_flag_tracks_window_fill():
    s = RollingMeanStd(5)
    for i in range(4):
        s.push(i)
        assert not s.ready
    s.push(4)
    assert s.ready
    assert s.n == 5  # never exceeds window


def test_rejects_degenerate_window():
    with pytest.raises(ValueError):
        RollingMeanStd(1)
