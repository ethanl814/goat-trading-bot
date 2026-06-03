# bot/framework/adapters/equities_alpaca.py
"""Equities adapter backed by Alpaca (the fully-wired reference asset class).

Scope note: this adapter currently acquires data by **polling** Alpaca's REST
trade endpoint on an interval and emitting `Trade` events. That keeps the live
path dependency-light and reuses the existing `AlpacaBroker` helpers. The
event-driven *engine* is unchanged either way — swapping in Alpaca's websocket
stream (lower latency, true push) is a contained change to `run()` here and is
the natural next wiring step. Execution is always simulated by `SimBroker`; this
adapter never places real orders.

Constraints declared per Alpaca equities: penny ticks, whole-share lots, ~0 fee,
shortable by default (borrow availability is a refinement to add later), session
hours via the Alpaca clock.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from bot.framework.adapters.base import MarketAdapter
from bot.framework.events import Trade
from bot.framework.instruments import AssetClass, InstrumentSpec, PriceKind
from bot.framework.sources import Emit

log = logging.getLogger(__name__)


class EquitiesAlpacaAdapter(MarketAdapter):
    name = "equities-alpaca"
    asset_class = AssetClass.EQUITY

    def __init__(self, symbols: list[str], *, poll_interval: float = 5.0, broker=None):
        self.symbols = symbols
        self.poll_interval = poll_interval
        # lazy import so backtests/tests never need Alpaca creds
        if broker is None:
            from bot.brokers.alpaca import AlpacaBroker
            broker = AlpacaBroker(paper=True)
        self._data = broker

    def build_specs(self, symbols: list[str]) -> list[InstrumentSpec]:
        return [
            InstrumentSpec(
                symbol=s,
                asset_class=AssetClass.EQUITY,
                price_kind=PriceKind.CONTINUOUS,
                tick_size=0.01,
                lot_size=1.0,
                taker_fee_bps=0.0,     # Alpaca equities are commission-free
                slippage_bps=2.0,
                shortable=True,
            )
            for s in symbols
        ]

    def is_open(self, now: datetime | None = None) -> bool:
        try:
            return bool(self._data.api.get_clock().is_open)
        except Exception:
            return True  # fail open; SimBroker still needs a price to fill

    async def run(self, emit: Emit, stop: asyncio.Event) -> None:
        log.info("polling Alpaca for %s every %ss", self.symbols, self.poll_interval)
        while not stop.is_set():
            for sym in self.symbols:
                # blocking REST call -> run in a thread so we don't stall the loop
                price = await asyncio.to_thread(self._data.current_price, sym)
                if price is not None:
                    await emit(Trade(instrument=sym, price=float(price)))
            try:
                await asyncio.wait_for(stop.wait(), timeout=self.poll_interval)
            except asyncio.TimeoutError:
                pass
