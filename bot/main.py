# bot/main.py
"""Entrypoint: build the engine, register signal sources + strategies, run.

    python -m bot.main

Everything heavy lives in bot/core (engine, registry) and bot/sources. Adding a
strategy needs no change here — it's auto-discovered. Adding a data source is
one `engine.add_source(...)` line.
"""
import logging
import os

from bot.brokers.alpaca import AlpacaBroker
from bot.core.engine import Engine
from bot.core.registry import discover_strategies
from bot.sources.clock import ClockSource
from bot.sources.edgar import EdgarSource

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("bot")

POLL_INTERVAL = float(os.getenv("POLL_INTERVAL", "180"))


def main() -> None:
    broker = AlpacaBroker(paper=True)
    log.info("Account equity: %s", broker.account_info().equity)

    strategies = discover_strategies(
        disabled=tuple(s for s in os.getenv("DISABLED_STRATEGIES", "").split(",") if s)
    )
    if not strategies:
        log.warning("no strategies discovered")

    engine = Engine(broker, strategies)
    engine.add_source(EdgarSource(interval=POLL_INTERVAL))   # filing signals (polled)
    engine.add_source(ClockSource(interval=POLL_INTERVAL))   # heartbeat -> exit checks

    # Low-latency real-time market data (opt-in). Enable once you have strategies
    # subscribing to BAR/QUOTE/TRADE events:
    #
    #   from bot.sources.alpaca_stream import AlpacaStreamSource
    #   engine.add_source(AlpacaStreamSource(symbols=["AAPL", "MSFT"], subscribe=("bars",)))

    engine.run()


if __name__ == "__main__":
    main()
