# tests/test_engine_endtoend.py
"""End-to-end: replay synthetic bars through the real engine and assert the
pipeline runs, trades, and produces an equity curve. Also exercises the
prediction-market adapter's resolution/settlement path through the engine."""
import asyncio
from datetime import timedelta

from bot.framework.adapters.prediction_market import PredictionMarketAdapter
from bot.framework.assembly import build_engine
from bot.framework.config import RunConfig
from bot.framework.instruments import AssetClass, InstrumentSpec, PriceKind
from bot.framework.replay import ReplaySource, generate_synthetic_bars


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


def test_prediction_market_resolution_flows_through_engine():
    symbols = ["MKT"]
    adapter = PredictionMarketAdapter(symbols, script={"MKT": ([0.3, 0.5, 0.7], 1.0)})
    specs = adapter.build_specs(symbols)
    engine = build_engine(RunConfig(), specs, sources=[adapter], record=False)

    asyncio.run(engine.run())

    # after resolution the contract is dropped from the universe
    assert "MKT" not in engine.universe
    assert "MKT" not in engine.states
