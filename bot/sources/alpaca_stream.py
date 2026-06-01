# bot/sources/alpaca_stream.py
"""Real-time market-data source over Alpaca's websocket.

This is the low-latency path: instead of polling every N seconds, Alpaca pushes
bars/quotes/trades to us as they happen and we turn them into Events the moment
they arrive. Strategies that subscribe to BAR/QUOTE/TRADE then react in the same
event loop the filings flow through.

Opt-in: not added in main.py by default. Free/paper accounts get IEX data
(`ALPACA_DATA_FEED=iex`); SIP requires a paid market-data subscription. Enable
by constructing this source with the symbols you want and adding it to the
engine.

Note: Alpaca's `Stream.run()` blocks and runs its own asyncio loop, so we give
this thread a fresh event loop before starting it.
"""
import asyncio
import logging
import os
from threading import Event as StopEvent
from typing import Callable

from bot.core.events import Event, EventType
from bot.sources.base import SignalSource

log = logging.getLogger(__name__)


class AlpacaStreamSource(SignalSource):
    name = "alpaca_stream"

    def __init__(self, symbols: list[str], subscribe: tuple[str, ...] = ("bars",),
                 feed: str | None = None):
        self.symbols = symbols
        self.subscribe = subscribe           # any of: "bars", "quotes", "trades"
        self.feed = feed or os.getenv("ALPACA_DATA_FEED", "iex")
        self._stream = None

    def run(self, emit: Callable[[Event], None], stop: StopEvent) -> None:
        import alpaca_trade_api as tradeapi

        asyncio.set_event_loop(asyncio.new_event_loop())

        self._stream = tradeapi.Stream(
            os.getenv("ALPACA_KEY_ID"),
            os.getenv("ALPACA_SECRET_KEY"),
            base_url=os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets"),
            data_feed=self.feed,
        )

        async def on_bar(bar):
            emit(Event(type=EventType.BAR, symbol=bar.symbol, source=self.name,
                       payload={"open": bar.open, "high": bar.high, "low": bar.low,
                                "close": bar.close, "volume": bar.volume}))

        async def on_quote(q):
            emit(Event(type=EventType.QUOTE, symbol=q.symbol, source=self.name,
                       payload={"bid": q.bid_price, "ask": q.ask_price}))

        async def on_trade(t):
            emit(Event(type=EventType.TRADE, symbol=t.symbol, source=self.name,
                       payload={"price": t.price, "size": t.size}))

        for sym in self.symbols:
            if "bars" in self.subscribe:
                self._stream.subscribe_bars(on_bar, sym)
            if "quotes" in self.subscribe:
                self._stream.subscribe_quotes(on_quote, sym)
            if "trades" in self.subscribe:
                self._stream.subscribe_trades(on_trade, sym)

        log.info("alpaca stream connecting | feed=%s symbols=%s subscribe=%s",
                 self.feed, self.symbols, self.subscribe)
        try:
            self._stream.run()  # blocks until the connection drops or stop
        except Exception:
            log.exception("alpaca stream stopped")
