# bot/framework/brokers_live.py
"""LiveAlpacaBroker — SCAFFOLD for real order routing through Alpaca.

Implements the same `Broker` interface as `SimBroker`, so the engine doesn't know
or care whether fills are simulated or real. It routes market orders via the
existing `AlpacaBroker` wrapper and reads positions/equity from the Alpaca account.

⚠️ This is scaffolding, not production-ready. Known gaps to close before trusting
it with money:
  - Fills are asynchronous: `submit` returns an *estimated* Fill at the reference
    price; the real fill price/qty arrive later via the trade-updates stream
    (not yet wired). Reconcile against actual fills before relying on PnL.
  - No partial-fill / rejection / retry handling.
  - Realized PnL here is read from the account, not reconstructed per-trade.
  - No idempotency/client-order-id dedup if the engine restarts.

It is gated behind `modes.make_broker` (LIVE requires ALLOW_LIVE_TRADING=yes), so
nothing routes real orders by accident.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from bot.framework.broker import Broker, Fill, Order, Position
from bot.framework.modes import TradingMode, make_data_broker
from bot.framework.state import MarketState

log = logging.getLogger(__name__)


class LiveAlpacaBroker(Broker):
    def __init__(self, mode: TradingMode, spec_map: dict):
        self.mode = mode
        self.specs = spec_map
        self._api = make_data_broker(mode)  # AlpacaBroker (also exposes .api)
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
        # estimated fill — real price/qty reconcile later via trade updates (TODO)
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
