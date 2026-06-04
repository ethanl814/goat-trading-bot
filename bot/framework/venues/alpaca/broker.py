# bot/framework/venues/alpaca/broker.py
"""LiveAlpacaBroker — SCAFFOLD for real equities order routing through Alpaca.

Same `Broker` interface as `SimBroker`, so the engine is agnostic. Routes market
orders and reads positions/equity from the Alpaca account.

⚠️ Scaffold, not production-ready. Fills are asynchronous: `submit` returns an
*estimated* Fill at the reference price; the real fill arrives later via the
trade-updates stream (not yet wired). No partial-fill / rejection / retry /
idempotency handling. Gated behind `Venue.make_broker` (LIVE needs
ALLOW_LIVE_TRADING=yes), so nothing routes by accident.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from bot.framework.broker import Broker, Fill, Order, Position
from bot.framework.modes import TradingMode
from bot.framework.state import MarketState
from bot.framework.venues.alpaca.creds import data_broker

log = logging.getLogger(__name__)


class LiveAlpacaBroker(Broker):
    def __init__(self, mode: TradingMode, spec_map: dict):
        self.mode = mode
        self.specs = spec_map
        self._api = data_broker(mode)
        self.realized = 0.0

    def submit(self, order: Order, state: MarketState) -> Fill | None:
        spec = self.specs[order.instrument]
        qty = int(spec.round_qty(order.qty))
        if qty == 0:
            return None
        ref = state.price()
        try:
            if qty > 0:
                self._api.submit_buy_market(order.instrument, abs(qty))
            else:
                self._api.submit_sell_market(order.instrument, abs(qty))
        except Exception:
            log.exception("live order failed: %s", order)
            return None
        return Fill(order.instrument, qty, ref or 0.0, 0.0,
                    datetime.now(timezone.utc), realized=0.0)

    def positions(self) -> dict[str, Position]:
        out: dict[str, Position] = {}
        try:
            for p in self._api.api.list_positions():
                out[p.symbol] = Position(p.symbol, float(p.qty), float(p.avg_entry_price))
        except Exception:
            log.exception("list_positions failed")
        return out

    def position_qty(self, symbol: str) -> float:
        p = self.positions().get(symbol)
        return p.qty if p else 0.0

    def equity(self, states: dict[str, MarketState]) -> float:
        try:
            return float(self._api.account_info().equity)
        except Exception:
            log.exception("account equity read failed")
            return 0.0

    def unrealized(self, states: dict[str, MarketState]) -> float:
        try:
            return sum(float(p.unrealized_pl) for p in self._api.api.list_positions())
        except Exception:
            return 0.0

    @property
    def cash(self) -> float:
        try:
            return float(self._api.account_info().cash)
        except Exception:
            return 0.0
