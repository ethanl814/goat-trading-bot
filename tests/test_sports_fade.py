# tests/test_sports_fade.py
"""RunReversalFade state machine, the Kalshi cost model, and EventFadeAllocator."""
import pytest

from bot.framework.allocator import EventFadeAllocator
from bot.framework.events import Trade
from bot.framework.signals.prediction_markets.sports_fade import RunReversalFade
from bot.framework.state import MarketState
from bot.framework.venues.kalshi.adapter import build_spec

SPEC = build_spec("KXTEST")


def _feed(sig, st, prices):
    for p in prices:
        ev = Trade(instrument="KXTEST", price=p)
        st.update(ev)
        sig.update(st, ev)


def _new(**kw):
    st = MarketState(SPEC)
    sig = RunReversalFade("KXTEST", SPEC, lookback=3, entry_drop=0.10,
                          reversion_frac=0.5, stop_drop=0.10, max_hold=3, **kw)
    return sig, st


def test_enters_on_fast_drop_and_exits_on_reversion():
    sig, st = _new()
    _feed(sig, st, [0.50, 0.50, 0.50, 0.50])   # quiet
    assert sig.value() == 0.0                    # FLAT
    _feed(sig, st, [0.38])                        # fast 12c drop -> enter
    # value() = conviction = drop/entry_drop = 0.12/0.10 = 1.2
    assert sig.state == "LONG" and sig.value() == pytest.approx(1.2)
    _feed(sig, st, [0.45])                        # recovers past 0.44 target -> exit
    assert sig.state == "FLAT" and sig.value() == 0.0
    assert sig.trades[-1]["reason"] == "reverted"
    assert sig.trades[-1]["move"] == pytest.approx(0.07)


def test_stops_out_when_move_continues():
    sig, st = _new()
    _feed(sig, st, [0.50, 0.50, 0.50, 0.50, 0.38])  # enter at 0.38
    assert sig.state == "LONG"
    _feed(sig, st, [0.27])                            # falls another 11c -> stop (<=0.28)
    assert sig.state == "FLAT"
    assert sig.trades[-1]["reason"] == "stopped"


def test_time_stop_closes_stale_trade():
    sig, st = _new()
    _feed(sig, st, [0.50, 0.50, 0.50, 0.50, 0.38])  # enter
    _feed(sig, st, [0.39, 0.40, 0.41])                # no revert/stop, 3 bars -> time stop
    assert sig.state == "FLAT"
    assert sig.trades[-1]["reason"] == "timed_out"


def test_no_entry_near_price_extremes():
    sig, st = _new(min_price=0.10, max_price=0.90)
    _feed(sig, st, [0.20, 0.20, 0.20, 0.20, 0.05])  # drop but lands below min_price
    assert sig.state == "FLAT"


# --- cost model -------------------------------------------------------------
def test_kalshi_fee_formula_rounds_up_to_cent():
    # ceil(0.07 * C * p * (1-p)) to next cent
    assert SPEC.fee(100, 0.50) == pytest.approx(1.75)   # 0.07*100*0.25 = 1.75
    assert SPEC.fee(100, 0.90) == pytest.approx(0.63)   # 0.07*100*0.09 = 0.63
    assert SPEC.fee(1, 0.50) == pytest.approx(0.02)     # ceil(0.0175*100)/100 = 0.02 (rounds up)


def test_slippage_is_absolute_and_clamped():
    assert SPEC.apply_slippage(0.40, buying=True) == pytest.approx(0.41)   # +1c half-spread
    assert SPEC.apply_slippage(0.40, buying=False) == pytest.approx(0.39)
    assert SPEC.apply_slippage(0.995, buying=True) == pytest.approx(1.0)   # clamped to settle_high


# --- allocator --------------------------------------------------------------
def test_event_fade_allocator_enters_fixed_count_and_exits():
    alloc = EventFadeAllocator(contracts=100)
    st = MarketState(SPEC)
    st.update(Trade(instrument="KXTEST", price=0.40))
    states, specs = {"KXTEST": st}, {"KXTEST": SPEC}
    assert alloc.targets({"KXTEST": 1.0}, states, specs, 10_000)["KXTEST"] == 100   # in -> long 100
    assert alloc.targets({"KXTEST": 0.0}, states, specs, 10_000)["KXTEST"] == 0     # flat -> exit


def test_event_fade_conviction_scaling():
    alloc = EventFadeAllocator(contracts=100, scale_by_conviction=True, conviction_cap=3.0)
    st = MarketState(SPEC)
    st.update(Trade(instrument="KXTEST", price=0.40))
    states, specs = {"KXTEST": st}, {"KXTEST": SPEC}
    assert alloc.targets({"KXTEST": 1.5}, states, specs, 10_000)["KXTEST"] == 150   # 1.5x conviction
    assert alloc.targets({"KXTEST": 9.0}, states, specs, 10_000)["KXTEST"] == 300   # capped at 3x


def test_avoid_band_skips_fee_peak_entries():
    sig, st = _new(avoid_lo=0.45, avoid_hi=0.55)
    # a 12c drop that lands at 0.50 (inside the avoid band) must NOT enter
    _feed(sig, st, [0.62, 0.62, 0.62, 0.62, 0.50])
    assert sig.state == "FLAT"
    # the same size drop landing at 0.38 (outside the band) DOES enter
    sig2, st2 = _new(avoid_lo=0.45, avoid_hi=0.55)
    _feed(sig2, st2, [0.50, 0.50, 0.50, 0.50, 0.38])
    assert sig2.state == "LONG"
