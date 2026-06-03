# bot/framework/sources.py
"""Event `Source` base + the live `ClockSource`.

A `Source` is anything that produces `Event`s onto the engine's async queue: a
live market adapter, a historical replay, or the clock. This is the *only* thing
that swaps between live and backtest modes — the engine, signals, allocator,
risk, and broker are identical in both.

`ClockSource` emits `Clock` events on a wall-clock interval to drive the
throttled decision step in live mode. (In backtest the replay source emits its
own Clock events on the data's timeline, so no wall clock is used.)
"""
from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from typing import Awaitable, Callable

from bot.framework.events import Clock, Event

Emit = Callable[[Event], Awaitable[None]]


class Source(ABC):
    name: str = "source"

    @abstractmethod
    async def run(self, emit: Emit, stop: asyncio.Event) -> None:
        """Produce events until `stop` is set. Must be resilient to its own
        transient errors. Returns when the source is exhausted (backtest) or
        when `stop` is set (live)."""
        raise NotImplementedError


class ClockSource(Source):
    name = "clock"

    def __init__(self, interval: float):
        self.interval = interval

    async def run(self, emit: Emit, stop: asyncio.Event) -> None:
        while not stop.is_set():
            await emit(Clock())
            try:
                # wake promptly if stop is set mid-interval
                await asyncio.wait_for(stop.wait(), timeout=self.interval)
            except asyncio.TimeoutError:
                pass
