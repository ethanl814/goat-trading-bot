# bot/framework/signals/base.py
"""The `Signal` abstract base — the framework's key extension point.

Contract (mirrors the spirit of the old `Strategy`, but for the continuous
market-state world):

  - One `Signal` *instance per instrument*; the engine fans a definition out to
    N independent stateful instances (one per universe member).
  - `update(state, event)` must be **O(1)** — fold the new event into rolling
    state (running sums, ring buffers, Welford). Never recompute a window.
  - `value()` returns a *normalized* number (a z-score / standardized signal),
    or `None` during warm-up. The allocator ranks these cross-sectionally; it
    never sees a raw price or a raw % move, which is what makes a flat
    "X% move" rule hard to express by accident.
  - `applies_to` lets a signal restrict itself to certain asset classes, or stay
    class-agnostic (empty tuple = applies to all).

A Signal decides nothing about position size or orders — that is the allocator's
and broker's job. This is the seam that keeps signals portable across assets.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from bot.framework.events import Event
from bot.framework.instruments import AssetClass, InstrumentSpec
from bot.framework.state import MarketState


class Signal(ABC):
    name: str = ""
    applies_to: tuple[AssetClass, ...] = ()  # empty => any asset class

    def __init__(self, instrument: str, spec: InstrumentSpec):
        self.instrument = instrument
        self.spec = spec

    @classmethod
    def supports(cls, asset_class: AssetClass) -> bool:
        return not cls.applies_to or asset_class in cls.applies_to

    @abstractmethod
    def update(self, state: MarketState, event: Event) -> None:
        """Fold one market event into rolling state. Must be O(1)."""
        raise NotImplementedError

    @abstractmethod
    def value(self) -> float | None:
        """Current normalized signal value, or None during warm-up."""
        raise NotImplementedError
