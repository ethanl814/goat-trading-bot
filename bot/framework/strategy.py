# bot/framework/strategy.py
"""A running strategy = a named bundle of (per-instrument signals + an allocator).

The engine runs a *list* of these concurrently against one shared book, so the
control panel can toggle several strategies on at once. Each owns its own signal
instances and allocator and gets a slice of capital (`capital_frac`); the engine
sums their target positions into one book and lets the RiskMonitor gate the total.

This is the framework analogue of the old `Strategy` ABC — but a strategy here is
*configuration over reusable parts* (which signal, which universe, how to size),
not a bespoke class. New strategies are declared in `control.py`, not coded.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from bot.framework.allocator import Allocator
from bot.framework.signals.base import Signal


@dataclass
class StrategyRunner:
    name: str
    signals: dict[str, Signal]          # symbol -> live signal instance
    allocator: Allocator
    capital_frac: float = 1.0
    enabled: bool = True
