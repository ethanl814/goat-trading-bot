# bot/framework/venues/kalshi/adapter.py
"""Kalshi live data adapter — polls market state and emits normalized events.

Emits `Quote` (yes bid/ask) + `Trade` (last price) per poll, and a `Resolution`
when a market settles (YES->1.0, NO->0.0) so the engine/SimBroker pays out and
the Universe drops the contract. REST polling keeps this dependency-light;
prediction markets move slowly enough that polling is fine — a websocket upgrade
(ticker/trade channels) is a contained change to `run()`.

Why poll, not stream, for v1: PM edges are about *mispricing vs your model*, not
microstructure, so 5–15s freshness is plenty. Execution is always via a `Broker`.
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from datetime import datetime

from bot.framework.adapters.base import MarketAdapter
from bot.framework.events import Quote, Resolution, Trade
from bot.framework.instruments import AssetClass, InstrumentSpec, PriceKind
from bot.framework.sources import Emit
from bot.framework.venues.kalshi.client import KalshiClient, to_float

log = logging.getLogger(__name__)

_SETTLED = {"settled", "finalized", "determined"}


class KalshiAdapter(MarketAdapter):
    name = "kalshi"
    asset_class = AssetClass.PREDICTION_MARKET

    def __init__(self, tickers: list[str], *, mode=None, poll_interval: float = 10.0,
                 client: KalshiClient | None = None):
        self.tickers = tickers
        self.poll_interval = poll_interval
        self._client = client or KalshiClient()
        self._resolved: set[str] = set()

    def build_specs(self, tickers: list[str]) -> list[InstrumentSpec]:
        return [build_spec(t) for t in tickers]

    def is_open(self, now: datetime | None = None) -> bool:
        try:
            return bool(self._client.exchange_status().get("trading_active", True))
        except Exception:
            return True

    async def run(self, emit: Emit, stop: asyncio.Event) -> None:
        log.info("polling Kalshi for %s every %ss (env=%s)",
                 self.tickers, self.poll_interval, self._client.env)
        while not stop.is_set():
            for ticker in self.tickers:
                if ticker in self._resolved:
                    continue
                try:
                    m = await asyncio.to_thread(self._client.get_market, ticker)
                except Exception as e:
                    log.warning("get_market(%s) failed: %s", ticker, e)
                    continue
                await self._emit_market(emit, ticker, m)
            with suppress(asyncio.TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=self.poll_interval)

    async def _emit_market(self, emit: Emit, ticker: str, m: dict) -> None:
        status = (m.get("status") or "").lower()
        if status in _SETTLED:
            result = (m.get("result") or "").lower()
            value = 1.0 if result == "yes" else 0.0
            await emit(Resolution(instrument=ticker, value=value))
            self._resolved.add(ticker)
            return
        bid = to_float(m.get("yes_bid_dollars") or m.get("yes_bid"))
        ask = to_float(m.get("yes_ask_dollars") or m.get("yes_ask"))
        if bid is not None and ask is not None:
            await emit(Quote(instrument=ticker, bid=bid, ask=ask))
        last = to_float(m.get("last_price_dollars") or m.get("last_price"))
        if last is not None:
            await emit(Trade(instrument=ticker, price=last))


def build_spec(ticker: str) -> InstrumentSpec:
    """Static spec for a Kalshi YES contract: probability price in [0,1], pays $1
    on YES resolve, long-only (buying NO is the short side; modeled later)."""
    return InstrumentSpec(
        symbol=ticker,
        asset_class=AssetClass.PREDICTION_MARKET,
        price_kind=PriceKind.PROBABILITY,
        tick_size=0.01,          # Kalshi prices in 1-cent increments
        lot_size=1.0,            # whole contracts
        contract_multiplier=1.0,  # 1 contract -> $1 at YES resolve
        taker_fee_bps=0.0,       # NOTE: real Kalshi fee ≈ ceil(0.07·p·(1-p)·count); add later
        slippage_bps=10.0,
        shortable=False,
        long_only=True,
        settle_low=0.0,
        settle_high=1.0,
        expires=True,
    )
