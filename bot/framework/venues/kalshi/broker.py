# bot/framework/venues/kalshi/broker.py
"""LiveKalshiBroker — SCAFFOLD for real Kalshi order routing.

Same `Broker` interface as `SimBroker`. Maps a signed framework `Order` to a
Kalshi YES-contract market order: qty > 0 -> buy YES `count`; qty < 0 -> sell YES.

⚠️ Scaffold. Gaps to close before trusting it: fills are async (returns an
estimated Fill); no NO-side handling (only YES long), partial fills, fee
reconciliation (Kalshi's per-trade fee ≈ ceil(0.07·p·(1-p)·count)), or
idempotency. Gated behind `Venue.make_broker` (LIVE needs ALLOW_LIVE_TRADING=yes).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from bot.framework.broker import Broker, Fill, Order, Position
from bot.framework.modes import TradingMode
from bot.framework.state import MarketState
from bot.framework.venues.kalshi.client import KalshiClient, to_float

log = logging.getLogger(__name__)


class LiveKalshiBroker(Broker):
    def __init__(self, mode: TradingMode, spec_map: dict):
        env = "prod" if mode is TradingMode.LIVE else "demo"
        self.mode = mode
        self.specs = spec_map
        self._client = KalshiClient(env=env)
        self.realized = 0.0

    def submit(self, order: Order, state: MarketState) -> Fill | None:
        spec = self.specs[order.instrument]
        qty = int(spec.round_qty(order.qty))
        if qty == 0:
            return None
        action = "buy" if qty > 0 else "sell"
        try:
            resp = self._client.create_order(ticker=order.instrument, side="yes",
                                             action=action, count=abs(qty))
        except Exception:
            log.exception("kalshi order REJECTED: %s", order)
            return None
        # best-effort read of the actual fill from the order response; fall back
        # to the reference price. NOTE: market orders fill ~immediately, but full
        # fill reconciliation (poll order status, partial fills) is still a TODO.
        o = (resp or {}).get("order", resp) or {}
        fill_price = (to_float(o.get("yes_price_dollars"))
                      or to_float(o.get("average_fill_price"))
                      or (state.price() or 0.0))
        filled = int(o.get("filled_count") or abs(qty))
        signed = filled if qty > 0 else -filled
        log.info("KALSHI %s %s x%d @ ~%.2f (order_id=%s status=%s)",
                 action.upper(), order.instrument, filled, fill_price,
                 o.get("order_id"), o.get("status"))
        return Fill(order.instrument, signed, fill_price, 0.0, datetime.now(timezone.utc), realized=0.0)

    def positions(self) -> dict[str, Position]:
        out: dict[str, Position] = {}
        try:
            data = self._client.get_positions()
            for p in data.get("market_positions", []):
                qty = float(p.get("position", 0))
                if qty:
                    out[p["ticker"]] = Position(p["ticker"], qty,
                                                to_float(p.get("market_exposure_dollars")) or 0.0)
        except Exception:
            log.exception("get_positions failed")
        return out

    def position_qty(self, symbol: str) -> float:
        p = self.positions().get(symbol)
        return p.qty if p else 0.0

    def equity(self, states: dict[str, MarketState]) -> float:
        try:
            return (to_float(self._client.get_balance().get("balance")) or 0.0)
        except Exception:
            log.exception("balance read failed")
            return 0.0

    def unrealized(self, states: dict[str, MarketState]) -> float:
        return 0.0  # TODO: derive from positions vs marks

    @property
    def cash(self) -> float:
        return self.equity({})
