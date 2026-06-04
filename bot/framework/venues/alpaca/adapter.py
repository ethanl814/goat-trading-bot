# bot/framework/venues/alpaca/adapter.py
"""Equities data adapter backed by Alpaca's websocket stream (REST-poll fallback).

Callbacks emit normalized events straight onto the engine's asyncio loop. On the
free IEX feed data is ~15 min delayed regardless of transport — the websocket
removes *our* lag, not the feed's; SIP (`ALPACA_DATA_FEED=sip`) is real-time.
Execution is always via a `Broker`; this adapter never places orders.
"""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import suppress
from datetime import datetime, timezone

from bot.framework.adapters.base import MarketAdapter
from bot.framework.events import Bar, Quote, Trade
from bot.framework.instruments import AssetClass, InstrumentSpec, PriceKind
from bot.framework.sources import Emit

log = logging.getLogger(__name__)


def _to_dt(ts) -> datetime:
    if isinstance(ts, datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    to_py = getattr(ts, "to_pydatetime", None)
    if to_py is not None:
        try:
            return to_py()
        except Exception:
            pass
    return datetime.now(timezone.utc)


class EquitiesAlpacaAdapter(MarketAdapter):
    name = "equities-alpaca"
    asset_class = AssetClass.EQUITY

    def __init__(self, symbols, *, subscribe=("trades", "quotes"), feed=None,
                 poll_interval=5.0, use_stream=True, broker=None):
        self.symbols = symbols
        self.subscribe = subscribe
        self.feed = feed or os.getenv("ALPACA_DATA_FEED", "iex")
        self.poll_interval = poll_interval
        self.use_stream = use_stream
        if broker is None:
            from bot.brokers.alpaca import AlpacaBroker
            broker = AlpacaBroker(paper=True)
        self._broker = broker
        self._stream = None

    def build_specs(self, symbols: list[str]) -> list[InstrumentSpec]:
        specs = []
        for s in symbols:
            shortable = True
            try:
                shortable = bool(getattr(self._broker.api.get_asset(s), "shortable", True))
            except Exception as e:
                log.debug("shortable lookup failed for %s (%s); assuming True", s, e)
            specs.append(InstrumentSpec(
                symbol=s, asset_class=AssetClass.EQUITY, price_kind=PriceKind.CONTINUOUS,
                tick_size=0.01, lot_size=1.0, taker_fee_bps=0.0, slippage_bps=2.0,
                shortable=shortable))
        return specs

    def is_open(self, now: datetime | None = None) -> bool:
        try:
            return bool(self._broker.api.get_clock().is_open)
        except Exception:
            return True

    async def run(self, emit: Emit, stop: asyncio.Event) -> None:
        if self.use_stream:
            try:
                await self._run_stream(emit, stop)
                return
            except Exception:
                log.exception("websocket path failed; falling back to REST polling")
        await self._run_poll(emit, stop)

    async def _run_stream(self, emit: Emit, stop: asyncio.Event) -> None:
        import alpaca_trade_api as tradeapi

        self._stream = tradeapi.Stream(
            os.getenv("ALPACA_KEY_ID"), os.getenv("ALPACA_SECRET_KEY"),
            base_url=os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets"),
            data_feed=self.feed)

        async def on_trade(t):
            await emit(Trade(instrument=t.symbol, ts=_to_dt(getattr(t, "timestamp", None)),
                             price=float(t.price), size=float(getattr(t, "size", 0) or 0)))

        async def on_quote(q):
            if q.bid_price is None or q.ask_price is None:
                return
            await emit(Quote(instrument=q.symbol, ts=_to_dt(getattr(q, "timestamp", None)),
                             bid=float(q.bid_price), ask=float(q.ask_price),
                             bid_size=float(getattr(q, "bid_size", 0) or 0),
                             ask_size=float(getattr(q, "ask_size", 0) or 0)))

        async def on_bar(b):
            await emit(Bar(instrument=b.symbol, ts=_to_dt(getattr(b, "timestamp", None)),
                           open=float(b.open), high=float(b.high), low=float(b.low),
                           close=float(b.close), volume=float(getattr(b, "volume", 0) or 0)))

        for sym in self.symbols:
            if "trades" in self.subscribe:
                self._stream.subscribe_trades(on_trade, sym)
            if "quotes" in self.subscribe:
                self._stream.subscribe_quotes(on_quote, sym)
            if "bars" in self.subscribe:
                self._stream.subscribe_bars(on_bar, sym)

        log.info("alpaca websocket connecting | feed=%s symbols=%s subscribe=%s",
                 self.feed, self.symbols, self.subscribe)
        runner = asyncio.create_task(self._stream._run_forever())
        stopper = asyncio.create_task(stop.wait())
        done, pending = await asyncio.wait({runner, stopper}, return_when=asyncio.FIRST_COMPLETED)
        with suppress(Exception):
            await self._stream.stop_ws()
        for task in pending:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        if runner in done:
            runner.result()

    async def _run_poll(self, emit: Emit, stop: asyncio.Event) -> None:
        log.info("polling Alpaca REST for %s every %ss", self.symbols, self.poll_interval)
        while not stop.is_set():
            for sym in self.symbols:
                price = await asyncio.to_thread(self._broker.current_price, sym)
                if price is not None:
                    await emit(Trade(instrument=sym, price=float(price)))
            with suppress(asyncio.TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=self.poll_interval)
