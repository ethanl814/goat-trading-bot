# bot/framework/broker.py
"""Broker interface + `SimBroker`.

The `Broker` interface is the seam for a future live broker. `SimBroker` is the
execution engine used in *both* modes (live-paper and backtest) — it fills
orders against current `MarketState`, applies adapter-declared fees/slippage/
tick/contract sizing generically, tracks cash + positions + realized/unrealized
PnL, and — crucially — handles **settlement/resolution payouts** via `settle`,
which is how prediction-market and futures positions terminate at a fixed value.

Avg-cost position accounting: adding to a position updates the average; reducing
or flipping realizes PnL on the closed quantity. No asset-class branches here —
everything class-specific is read off the `InstrumentSpec`.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone

from bot.framework.instruments import InstrumentSpec
from bot.framework.state import MarketState

log = logging.getLogger(__name__)


@dataclass
class Order:
    instrument: str
    qty: float  # signed: + buy, - sell


@dataclass
class Fill:
    instrument: str
    qty: float
    price: float
    fee: float
    ts: datetime
    realized: float = 0.0


@dataclass
class Position:
    instrument: str
    qty: float = 0.0
    avg_price: float = 0.0


class Broker(ABC):
    @abstractmethod
    def submit(self, order: Order, state: MarketState) -> Fill | None: ...
    @abstractmethod
    def positions(self) -> dict[str, Position]: ...
    @abstractmethod
    def equity(self, states: dict[str, MarketState]) -> float: ...


class SimBroker(Broker):
    def __init__(self, starting_cash: float, specs: dict[str, InstrumentSpec]):
        self.cash = float(starting_cash)
        self.specs = specs
        self.realized = 0.0
        self._pos: dict[str, Position] = {}

    # --- queries -------------------------------------------------------------
    def positions(self) -> dict[str, Position]:
        return {s: p for s, p in self._pos.items() if p.qty != 0}

    def position_qty(self, symbol: str) -> float:
        p = self._pos.get(symbol)
        return p.qty if p else 0.0

    def market_value(self, states: dict[str, MarketState]) -> float:
        total = 0.0
        for sym, pos in self._pos.items():
            st = states.get(sym)
            price = st.price() if st else None
            if price is None:
                price = pos.avg_price  # fall back to cost if no live price
            total += pos.qty * price * self.specs[sym].contract_multiplier
        return total

    def unrealized(self, states: dict[str, MarketState]) -> float:
        total = 0.0
        for sym, pos in self._pos.items():
            st = states.get(sym)
            price = st.price() if st else None
            if price is None:
                continue
            total += (price - pos.avg_price) * pos.qty * self.specs[sym].contract_multiplier
        return total

    def equity(self, states: dict[str, MarketState]) -> float:
        return self.cash + self.market_value(states)

    # --- execution -----------------------------------------------------------
    def submit(self, order: Order, state: MarketState) -> Fill | None:
        spec = self.specs[order.instrument]
        qty = spec.round_qty(order.qty)
        if qty == 0:
            return None
        ref = state.price()
        if ref is None or ref <= 0:
            log.debug("no price for %s; order skipped", order.instrument)
            return None

        # slippage moves the fill against us, in the direction of the trade
        slip = spec.slippage_bps / 1e4
        fill_price = spec.round_price(ref * (1 + slip) if qty > 0 else ref * (1 - slip))
        fee = spec.fee(qty, fill_price, taker=True)
        realized = self._apply(spec, qty, fill_price)
        self.cash += -qty * fill_price * spec.contract_multiplier - fee
        self.realized += realized
        fill = Fill(order.instrument, qty, fill_price, fee,
                    datetime.now(timezone.utc), realized)
        return fill

    def _apply(self, spec: InstrumentSpec, qty: float, price: float) -> float:
        """Update the position for a signed fill; return realized PnL."""
        pos = self._pos.setdefault(spec.symbol, Position(spec.symbol))
        mult = spec.contract_multiplier
        realized = 0.0

        if pos.qty == 0 or (pos.qty > 0) == (qty > 0):
            # opening or adding in the same direction -> blend average cost
            new_qty = pos.qty + qty
            pos.avg_price = (pos.avg_price * pos.qty + price * qty) / new_qty
            pos.qty = new_qty
        else:
            # reducing, closing, or flipping -> realize on the closed quantity
            closing = min(abs(qty), abs(pos.qty))
            direction = 1.0 if pos.qty > 0 else -1.0
            realized = (price - pos.avg_price) * closing * direction * mult
            new_qty = pos.qty + qty
            if new_qty == 0:
                pos.avg_price = 0.0
            elif (new_qty > 0) != (pos.qty > 0):
                pos.avg_price = price  # flipped: residual opens at fill price
            pos.qty = new_qty
        return realized

    # --- settlement / resolution --------------------------------------------
    def settle(self, symbol: str, value: float) -> Fill | None:
        """Terminate a position at a fixed value (prediction-market resolve,
        future expiry). Closes the whole position at `value` and realizes PnL."""
        pos = self._pos.get(symbol)
        if not pos or pos.qty == 0:
            self._pos.pop(symbol, None)
            return None
        spec = self.specs[symbol]
        mult = spec.contract_multiplier
        realized = (value - pos.avg_price) * pos.qty * mult
        self.cash += pos.qty * value * mult
        self.realized += realized
        closed_qty = -pos.qty
        self._pos.pop(symbol, None)
        log.info("SETTLE %s @ %s | realized=%.2f", symbol, value, realized)
        return Fill(symbol, closed_qty, value, 0.0, datetime.now(timezone.utc), realized)
