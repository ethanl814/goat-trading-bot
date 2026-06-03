# tests/test_simbroker.py
"""SimBroker fill / fee / PnL accounting, plus the settlement path."""
import pytest

from bot.framework.broker import Order, SimBroker
from bot.framework.events import Trade
from bot.framework.instruments import AssetClass, InstrumentSpec, PriceKind
from bot.framework.state import MarketState

EQ = InstrumentSpec(symbol="X", asset_class=AssetClass.EQUITY,
                    taker_fee_bps=10.0, slippage_bps=0.0, tick_size=0.0)
PM = InstrumentSpec(symbol="Y", asset_class=AssetClass.PREDICTION_MARKET,
                    price_kind=PriceKind.PROBABILITY, long_only=True,
                    shortable=False, slippage_bps=0.0, tick_size=0.0)


def _state(spec, price):
    st = MarketState(spec)
    st.update(Trade(instrument=spec.symbol, price=price))
    return st


def test_buy_then_sell_realizes_pnl_and_fees():
    b = SimBroker(10_000, {"X": EQ})
    st = _state(EQ, 100.0)

    buy = b.submit(Order("X", 10), st)
    assert buy.qty == 10 and buy.price == 100.0
    # fee = 10 * 100 * 10bps(=0.001) = $1; cash = 10000 - 1000 - 1
    assert b.cash == pytest.approx(8999.0)
    assert b.position_qty("X") == 10

    st2 = _state(EQ, 110.0)
    sell = b.submit(Order("X", -10), st2)
    # realized = (110-100)*10 = 100 (gross of the exit fee)
    assert sell.realized == pytest.approx(100.0)
    assert b.position_qty("X") == 0
    # cash back: 8999 + 1100 - fee(110*10*0.001=1.1) = 10097.9
    assert b.cash == pytest.approx(10_097.9)
    assert b.realized == pytest.approx(100.0)


def test_equity_tracks_unrealized():
    b = SimBroker(10_000, {"X": EQ})
    b.submit(Order("X", 10), _state(EQ, 100.0))
    states = {"X": _state(EQ, 120.0)}
    # cash 8999 + position mark 10*120 = 1200 -> 10199
    assert b.equity(states) == pytest.approx(10_199.0)
    assert b.unrealized(states) == pytest.approx(200.0)


def test_settlement_resolves_to_one():
    b = SimBroker(10_000, {"Y": PM})
    b.submit(Order("Y", 100), _state(PM, 0.40))  # buy 100 YES @ 0.40 -> cash -40
    assert b.cash == pytest.approx(9_960.0)
    fill = b.settle("Y", 1.0)                     # resolves YES
    assert fill.realized == pytest.approx((1.0 - 0.40) * 100)  # +60
    assert b.position_qty("Y") == 0
    assert b.cash == pytest.approx(10_060.0)


def test_settlement_resolves_to_zero_is_total_loss():
    b = SimBroker(10_000, {"Y": PM})
    b.submit(Order("Y", 100), _state(PM, 0.40))
    b.settle("Y", 0.0)
    assert b.cash == pytest.approx(9_960.0)        # the 40 paid is gone
    assert b.realized == pytest.approx(-40.0)


def test_long_only_short_order_still_fills_but_allocator_guards():
    # SimBroker itself fills what it's told; the long-only guard lives in the
    # allocator. Here we just confirm the spec flag is readable.
    assert PM.can_short is False
