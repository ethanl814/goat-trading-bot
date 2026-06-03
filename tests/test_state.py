# tests/test_state.py
"""MarketState degrades across trade/quote/bar and reports the right reference price."""
from bot.framework.events import Bar, Quote, Trade
from bot.framework.instruments import AssetClass, InstrumentSpec
from bot.framework.state import MarketState

SPEC = InstrumentSpec(symbol="X", asset_class=AssetClass.EQUITY)


def test_trade_sets_last_price():
    st = MarketState(SPEC)
    assert st.price() is None
    moved = st.update(Trade(instrument="X", price=10.0))
    assert moved and st.price() == 10.0


def test_quote_mid_takes_priority_over_last_trade():
    st = MarketState(SPEC)
    st.update(Trade(instrument="X", price=10.0))
    st.update(Quote(instrument="X", bid=11.0, ask=13.0))
    assert st.mid == 12.0
    assert st.price() == 12.0  # mid preferred when a book exists


def test_bar_updates_last_to_close():
    st = MarketState(SPEC)
    st.update(Bar(instrument="X", open=9, high=11, low=8, close=10.5))
    assert st.price() == 10.5
    assert st.last_bar.high == 11


def test_update_reports_price_movement():
    st = MarketState(SPEC)
    assert st.update(Trade(instrument="X", price=10.0)) is True
    assert st.update(Trade(instrument="X", price=10.0)) is False
    assert st.update(Trade(instrument="X", price=10.5)) is True
