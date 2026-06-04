# tests/test_engine_endtoend.py
"""End-to-end: replay synthetic bars through the real engine and assert the
pipeline runs, trades, and produces an equity curve. Also exercises the
prediction-market adapter's resolution/settlement path through the engine."""
import asyncio
from datetime import timedelta

from bot.framework.assembly import build_engine
from bot.framework.config import RunConfig
from bot.framework.events import Resolution, Trade
from bot.framework.instruments import AssetClass, InstrumentSpec, PriceKind
from bot.framework.replay import ReplaySource, generate_synthetic_bars
from bot.framework.sources import Source
from bot.framework.venues.kalshi.adapter import build_spec as kalshi_spec


def test_backtest_runs_and_trades(tmp_path):
    symbols = ["AAA", "BBB", "CCC", "DDD"]
    specs = [InstrumentSpec(symbol=s, asset_class=AssetClass.EQUITY, slippage_bps=1.0)
             for s in symbols]
    events = generate_synthetic_bars(symbols, n=300, seed=1)
    source = ReplaySource(events, decision_interval=timedelta(minutes=5))
    engine = build_engine(RunConfig(), specs, sources=[source], record=False)

    asyncio.run(engine.run())

    # the reference signal + allocator should have opened positions at some point
    # and the broker equity should be finite and computed.
    eq = engine.broker.equity(engine.states)
    assert eq > 0
    # at least one fill occurred (realized changed or positions held)
    assert engine.broker.realized != 0 or engine.broker.positions()


class _ScriptedPMSource(Source):
    """Tiny inline source: a few probability prints, then a YES resolution."""
    name = "scripted-pm"

    def __init__(self, ticker, prices, resolve):
        self.ticker, self.prices, self.resolve = ticker, prices, resolve

    async def run(self, emit, stop):
        for p in self.prices:
            await emit(Trade(instrument=self.ticker, price=p))
        await emit(Resolution(instrument=self.ticker, value=self.resolve))


def test_prediction_market_resolution_flows_through_engine():
    # uses the real Kalshi InstrumentSpec (PROBABILITY, long-only, settles 0..1)
    specs = [kalshi_spec("MKT")]
    source = _ScriptedPMSource("MKT", [0.3, 0.5, 0.7], resolve=1.0)
    engine = build_engine(RunConfig(), specs, sources=[source], record=False)

    asyncio.run(engine.run())

    # after resolution the contract is dropped from the universe + state
    assert "MKT" not in engine.universe
    assert "MKT" not in engine.states
