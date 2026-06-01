# bot/core/events.py
"""The normalized event model that flows through the engine.

A *signal source* (SEC feed, price websocket, a clock, …) produces `Event`s.
Strategies declare which `EventType`s they care about and receive matching
events. Decoupling "what produced the signal" from "what reacts to it" is what
lets you add new data sources and new strategies independently.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class EventType(str, Enum):
    FILING = "filing"   # a new SEC filing (EDGAR)
    BAR = "bar"         # an OHLCV bar closed (streaming or polled)
    QUOTE = "quote"     # top-of-book bid/ask update
    TRADE = "trade"     # a print on the tape
    TICK = "tick"       # engine heartbeat (drives periodic work like exits)


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Event:
    type: EventType
    symbol: str | None
    payload: dict[str, Any] = field(default_factory=dict)
    ts: datetime = field(default_factory=_now)
    source: str = ""


@dataclass
class Order:
    """A strategy's decision. The engine, not the strategy, executes it."""
    symbol: str
    qty: int
    side: str = "buy"            # "buy" | "sell"
    entry_price: float | None = None
    strategy: str = ""
    meta: dict[str, Any] = field(default_factory=dict)
