# tests/test_risk.py
"""RiskMonitor: gross-exposure scaling and the drawdown kill switch."""
import pytest

from bot.framework.events import Trade
from bot.framework.instruments import AssetClass, InstrumentSpec
from bot.framework.risk import RiskLimits, RiskMonitor
from bot.framework.state import MarketState

SPEC = InstrumentSpec(symbol="X", asset_class=AssetClass.EQUITY, lot_size=0.0)  # no rounding


def _states(price):
    st = MarketState(SPEC)
    st.update(Trade(instrument="X", price=price))
    return {"X": st}


def test_gross_cap_scales_targets_down():
    rm = RiskMonitor(RiskLimits(gross_cap_frac=1.0, net_cap_frac=10.0, max_drawdown_frac=1.0))
    specs = {"X": SPEC}
    equity = 1_000.0
    # target 20 shares @ $100 = $2000 gross = 2x equity; cap is 1x -> halve to 10
    out = rm.gate({"X": 20.0}, _states(100.0), specs, equity)
    assert out["X"] == pytest.approx(10.0)


def test_kill_switch_trips_on_drawdown_and_flattens():
    rm = RiskMonitor(RiskLimits(max_drawdown_frac=0.20))
    assert rm.check_drawdown(1_000.0) is False     # sets peak
    assert rm.check_drawdown(900.0) is False        # -10%, under limit
    assert rm.check_drawdown(750.0) is True         # -25% -> trips
    assert rm.halted is True
    # once halted, gate flattens any proposed targets
    flat = rm.gate({"X": 50.0}, _states(100.0), {"X": SPEC}, 750.0)
    assert flat == {"X": 0.0}


def test_per_class_cap_applies():
    limits = RiskLimits(gross_cap_frac=99.0, net_cap_frac=99.0,
                        max_drawdown_frac=1.0,
                        per_class_gross_frac={AssetClass.EQUITY: 1.0})
    rm = RiskMonitor(limits)
    out = rm.gate({"X": 20.0}, _states(100.0), {"X": SPEC}, 1_000.0)
    assert out["X"] == pytest.approx(10.0)  # class cap 1x equity -> $1000 -> 10 shares
