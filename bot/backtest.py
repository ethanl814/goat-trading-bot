# bot/backtest.py
"""Backtest entrypoint — replays stored (or synthetic) bars through the SAME core.

    python -m bot.backtest                 # synthetic data, runs out of the box
    python -m bot.backtest data/bars.csv   # replay a CSV (ts,symbol,o,h,l,c,v)

Produces an equity curve in logs/ comparable to a live run, then prints the
analysis summary (PnL / Sharpe / max drawdown / turnover). Needs no credentials.
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from datetime import timedelta

from bot.framework.assembly import build_engine
from bot.framework.config import RunConfig
from bot.framework.instruments import AssetClass, InstrumentSpec, PriceKind
from bot.framework.replay import ReplaySource, generate_synthetic_bars, load_bars_csv

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("bot.backtest")

DEFAULT_UNIVERSE = ["AAA", "BBB", "CCC", "DDD", "EEE"]


def _specs(symbols: list[str]) -> list[InstrumentSpec]:
    # synthetic equities-like specs (the replay path is asset-class-agnostic)
    return [InstrumentSpec(symbol=s, asset_class=AssetClass.EQUITY,
                           price_kind=PriceKind.CONTINUOUS, slippage_bps=2.0)
            for s in symbols]


async def _run(path: str | None) -> None:
    cfg = RunConfig()
    if path:
        events = load_bars_csv(path)
        symbols = sorted({e.instrument for e in events})
        log.info("replaying %d events over %s from %s", len(events), symbols, path)
    else:
        symbols = DEFAULT_UNIVERSE
        events = generate_synthetic_bars(symbols, n=600)
        log.info("no data file — generated %d synthetic bars over %s", len(events), symbols)

    specs = _specs(symbols)
    source = ReplaySource(events, decision_interval=timedelta(minutes=5))
    engine = build_engine(cfg, specs, sources=[source], run_id="backtest")
    await engine.run()


def main() -> None:
    path = sys.argv[1] if len(sys.argv) > 1 else None
    asyncio.run(_run(path))
    # analysis summary
    from scripts.analyze import summarize
    summarize("logs/equity_backtest.csv", fills_path="logs/fills_backtest.csv")


if __name__ == "__main__":
    main()
