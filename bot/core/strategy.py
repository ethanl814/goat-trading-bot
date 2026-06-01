# bot/core/strategy.py
"""Base class every strategy implements.

Contract:
  - `name`       : unique id (used in logs, position records, enable/disable).
  - `subscribes` : the EventTypes this strategy wants to receive.
  - `on_event`   : given an event + broker, return an Order or None.

A strategy never touches order submission, position bookkeeping, or exits —
the engine owns those. A strategy only turns *signals* into *decisions*. This
keeps strategies small, pure-ish, and testable.
"""
from abc import ABC, abstractmethod

from bot.brokers.alpaca import AlpacaBroker
from bot.core.events import Event, EventType, Order


class Strategy(ABC):
    name: str = ""
    subscribes: tuple[EventType, ...] = ()
    enabled: bool = True

    @abstractmethod
    def on_event(self, event: Event, broker: AlpacaBroker) -> Order | None:
        """React to a single event. Return an Order to act, or None to pass."""
        raise NotImplementedError
