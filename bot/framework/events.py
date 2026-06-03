# bot/framework/events.py
"""The normalized event vocabulary that flows through the engine.

Every data source — equity websocket, crypto stream, prediction-market feed,
historical replay — translates its native messages into *these* types. The core
speaks only this vocabulary, which is how one engine serves four asset classes.

Type hierarchy (kw-only dataclasses so subclasses can add required fields
without fighting base-class field-ordering):

    Event                       base: instrument id + timestamp
    ├─ Trade                    a print on the tape (price, size)
    ├─ Quote                    top-of-book (bid/ask) — degrades to last where no book
    ├─ Bar                      a closed OHLCV bar (the backtestable granularity)
    ├─ Resolution               first-class: an instrument settles at a fixed value
    │                           (prediction-market resolve, future expiry/settle)
    └─ Clock                    decision heartbeat — drives the throttled allocator step

`Resolution` is deliberately a first-class event, not an edge case: it is the
path by which positions terminate at a known value and instruments leave the
universe. See SimBroker.settle and Engine._on_resolution.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import ClassVar


class EventType(str, Enum):
    TRADE = "trade"
    QUOTE = "quote"
    BAR = "bar"
    RESOLUTION = "resolution"
    CLOCK = "clock"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(kw_only=True)
class Event:
    instrument: str | None = None
    ts: datetime = field(default_factory=_utcnow)
    type: ClassVar[EventType]  # set by each concrete subclass


@dataclass(kw_only=True)
class Trade(Event):
    price: float
    size: float = 0.0
    type: ClassVar[EventType] = EventType.TRADE


@dataclass(kw_only=True)
class Quote(Event):
    bid: float
    ask: float
    bid_size: float = 0.0
    ask_size: float = 0.0
    type: ClassVar[EventType] = EventType.QUOTE

    @property
    def mid(self) -> float | None:
        if self.bid is None or self.ask is None:
            return None
        return (self.bid + self.ask) / 2.0


@dataclass(kw_only=True)
class Bar(Event):
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    type: ClassVar[EventType] = EventType.BAR


@dataclass(kw_only=True)
class Resolution(Event):
    """An instrument settles/expires at a fixed value (e.g. a prediction-market
    contract resolves to 0 or 1; a future settles at its final price)."""
    value: float
    type: ClassVar[EventType] = EventType.RESOLUTION


@dataclass(kw_only=True)
class Clock(Event):
    """Decision heartbeat. The engine runs the (expensive) allocator step only
    on Clock events, conflating any burst of market events into one decision
    against the latest state. In live mode a ClockSource emits these on a wall
    timer; in backtest the replay source interleaves them on the data's clock."""
    type: ClassVar[EventType] = EventType.CLOCK


# Market data events that update per-instrument state (everything but Clock/Resolution).
MARKET_EVENTS = (Trade, Quote, Bar)
