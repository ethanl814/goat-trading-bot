# bot/framework/adapters/prediction_market.py
"""Prediction-market adapter — a STUB that proves the asset-class seam.

It is deliberately not wired to a live venue (Kalshi/Polymarket come next). Its
purpose is to demonstrate that a genuinely different market fits the core with
*only* an adapter, no core edits — the abstraction is shown, not asserted.

What's different about this class, and how the abstraction absorbs it:
  - **Price is a probability in [0,1]** → `PriceKind.PROBABILITY`, settlement
    bounds [0,1]. MarketState/allocator/risk treat it as any other price.
  - **Positions resolve at a fixed value** → the adapter emits a `Resolution`
    event; `SimBroker.settle` pays out and the `Universe` drops the contract.
    This is the path futures expiry uses too.
  - **Long-only, capital-capped** → declared via `long_only=True` /
    `max_position_qty`; the allocator and risk monitor respect it generically.
  - **Universe churns** → contracts list and resolve, handled by Universe.add /
    .remove driven off Resolution.

The `run()` below replays a tiny scripted lifecycle (a few quotes, then a
resolution) so the end-to-end settlement path is demonstrable without a venue.
Replace it with a real websocket/poll client when wiring Kalshi/Polymarket.
"""
from __future__ import annotations

import asyncio
import logging

from bot.framework.adapters.base import MarketAdapter
from bot.framework.events import Resolution, Trade
from bot.framework.instruments import AssetClass, InstrumentSpec, PriceKind
from bot.framework.sources import Emit

log = logging.getLogger(__name__)


class PredictionMarketAdapter(MarketAdapter):
    name = "prediction-market-stub"
    asset_class = AssetClass.PREDICTION_MARKET

    def __init__(self, symbols: list[str], *, script: dict | None = None):
        self.symbols = symbols
        # optional {symbol: (path_of_prices, resolve_value)} scripted lifecycle
        self.script = script or {}

    def build_specs(self, symbols: list[str]) -> list[InstrumentSpec]:
        return [
            InstrumentSpec(
                symbol=s,
                asset_class=AssetClass.PREDICTION_MARKET,
                price_kind=PriceKind.PROBABILITY,
                tick_size=0.01,
                lot_size=1.0,            # 1 contract pays $1 on YES resolve
                taker_fee_bps=0.0,
                shortable=False,
                long_only=True,          # many prediction markets are long-only
                max_position_qty=1000,   # capital cap per contract
                expires=True,
                settle_low=0.0,
                settle_high=1.0,
            )
            for s in symbols
        ]

    async def run(self, emit: Emit, stop: asyncio.Event) -> None:
        log.warning("prediction-market adapter is a STUB (replays a scripted "
                    "lifecycle). Wire Kalshi/Polymarket here to go live.")
        for sym in self.symbols:
            prices, resolve = self.script.get(sym, ([0.4, 0.45, 0.5], 1.0))
            for p in prices:
                if stop.is_set():
                    return
                await emit(Trade(instrument=sym, price=float(p)))
            await emit(Resolution(instrument=sym, value=float(resolve)))
