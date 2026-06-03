# bot/framework/state.py
"""Per-instrument maintained market state + incremental rolling statistics.

`MarketState` is the latest-known view of one instrument that signals read from.
Where a full book exists it holds bid/ask; where only trades or bars arrive it
degrades gracefully to last/mid/close. It is updated O(1) per event.

`RollingMeanStd` is the workhorse for the framework's *incremental* discipline:
a fixed sliding window with running sum / sum-of-squares so mean and variance
update in O(1) — never recompute the window from scratch. Signals should build
on this rather than re-summing arrays per tick (see tests/test_signal_equivalence
for the incremental-vs-naive guarantee).
"""
from __future__ import annotations

from collections import deque

from bot.framework.events import Bar, Event, Quote, Trade
from bot.framework.instruments import InstrumentSpec


class RollingMeanStd:
    """Mean/variance over the last `window` pushed values, updated in O(1)."""

    def __init__(self, window: int):
        if window < 2:
            raise ValueError("window must be >= 2")
        self.window = window
        self._buf: deque[float] = deque()
        self._sum = 0.0
        self._sumsq = 0.0

    def push(self, x: float) -> None:
        self._buf.append(x)
        self._sum += x
        self._sumsq += x * x
        if len(self._buf) > self.window:
            old = self._buf.popleft()
            self._sum -= old
            self._sumsq -= old * old

    @property
    def n(self) -> int:
        return len(self._buf)

    @property
    def ready(self) -> bool:
        return self.n >= self.window

    def mean(self) -> float:
        return self._sum / self.n if self.n else 0.0

    def var(self) -> float:
        if self.n < 2:
            return 0.0
        m = self.mean()
        # population sum-of-squares form; clamp tiny negatives from fp error
        return max((self._sumsq - self.n * m * m) / (self.n - 1), 0.0)

    def std(self) -> float:
        return self.var() ** 0.5


class MarketState:
    """Latest market view for one instrument. `update` is O(1)."""

    def __init__(self, spec: InstrumentSpec):
        self.spec = spec
        self.last_trade: float | None = None
        self.bid: float | None = None
        self.ask: float | None = None
        self.last_bar: Bar | None = None
        self.last_ts = None

    def update(self, event: Event) -> bool:
        """Apply one market event. Returns True if the reference price moved."""
        before = self.price()
        if isinstance(event, Trade):
            self.last_trade = event.price
        elif isinstance(event, Quote):
            self.bid, self.ask = event.bid, event.ask
        elif isinstance(event, Bar):
            self.last_bar = event
            self.last_trade = event.close
        self.last_ts = event.ts
        return self.price() != before

    @property
    def mid(self) -> float | None:
        if self.bid is not None and self.ask is not None:
            return (self.bid + self.ask) / 2.0
        return None

    def price(self) -> float | None:
        """Best available reference price: mid if a book exists, else last trade/close."""
        return self.mid if self.mid is not None else self.last_trade
