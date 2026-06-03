# bot/framework/signals/reversion.py
"""Reference signal: short-window return reversion (z-score).

Its only job is to exercise the full pipeline end to end — it is *not* meant to
be profitable. It's chosen as the reference because it works on the lowest common
denominator of data (a price series), so it runs on bars *or* trades and is
backtestable on cheap OHLCV data across every asset class. (Order-book imbalance
would be a better live signal but isn't backtestable without scarce L2 history —
hence reversion as the portable default.)

Incremental by construction: each price update computes the 1-step return and
folds it into a `RollingMeanStd` window in O(1). The emitted value is the
*negative* z-score of the latest return — recent abnormal up-moves → negative
(expect mean reversion down) and vice-versa. Already vol-normalized, so the
cross-sectional allocator can rank it directly.
"""
from __future__ import annotations

from bot.framework.events import Event
from bot.framework.signals.base import Signal
from bot.framework.state import MarketState, RollingMeanStd
from bot.framework.registry import register


@register("reversion")
class ShortWindowReversion(Signal):
    name = "reversion"
    # applies_to empty => runs on any asset class (continuous or probability price)

    def __init__(self, instrument, spec, window: int = 20):
        super().__init__(instrument, spec)
        self.window = window
        self._stats = RollingMeanStd(window)
        self._prev_price: float | None = None
        self._value: float | None = None

    def update(self, state: MarketState, event: Event) -> None:
        price = state.price()
        if price is None or price <= 0:
            return
        if self._prev_price is not None and self._prev_price > 0:
            ret = (price - self._prev_price) / self._prev_price
            # z-score the new return against the window *before* folding it in,
            # so the statistic isn't contaminated by the point it scores.
            if self._stats.ready and self._stats.std() > 0:
                z = (ret - self._stats.mean()) / self._stats.std()
                self._value = -z
            self._stats.push(ret)
        self._prev_price = price

    def value(self) -> float | None:
        return self._value
