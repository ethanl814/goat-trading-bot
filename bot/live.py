# bot/live.py
"""Live-paper entrypoint for the framework.

    python -m bot.live AAPL MSFT NVDA AMD INTC

Stands up the async engine on equities (Alpaca data → SimBroker fills), runs the
reference signal + cross-sectional allocator under book-level risk caps, and
writes an equity curve to logs/. Ctrl-C flips the stop event for a clean unwind.

This is the *same* engine/signal/allocator/risk/broker the backtest runs — only
the data source differs (live Alpaca adapter vs replay).
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys

from bot.framework.adapters.equities_alpaca import EquitiesAlpacaAdapter
from bot.framework.assembly import build_engine
from bot.framework.config import RunConfig
from bot.framework.sources import ClockSource

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("bot.live")

DEFAULT_UNIVERSE = ["AAPL", "MSFT", "NVDA", "AMD", "INTC"]


async def _run(symbols: list[str]) -> None:
    cfg = RunConfig()
    adapter = EquitiesAlpacaAdapter(symbols, poll_interval=5.0)
    specs = adapter.build_specs(symbols)
    clock = ClockSource(cfg.decision_interval_seconds)

    engine = build_engine(cfg, specs, sources=[adapter, clock])

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            pass  # not available on some platforms
    await engine.run(stop)


def main() -> None:
    symbols = sys.argv[1:] or DEFAULT_UNIVERSE
    log.info("live-paper universe: %s", symbols)
    asyncio.run(_run(symbols))


if __name__ == "__main__":
    main()
