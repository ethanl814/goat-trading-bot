# bot/framework/signals/equities/reversion.py
# ============================================================================
# STRATEGY CARD
#   name      : reversion          desk: equities         status: REFERENCE
#   thesis    : (none — plumbing) short-window return mean-reversion
#   signal    : negative z-score of the latest 1-step return (vol-normalized)
#   entry/exit: none of its own — a cross-sectional allocator ranks the value
#               and goes long top slice / short bottom slice
#   risk      : book-level only (RiskMonitor: gross/net caps + drawdown kill
#               switch); no per-name stop. Sizing by the allocator.
#   costs     : not cost-tuned; this only validates the pipeline end to end.
# ============================================================================
"""Reference signal — exercises the full pipeline, NOT meant to be profitable.

Chosen because it works on the lowest common denominator of data (a price
series), so it runs on bars or trades and backtests on cheap OHLCV anywhere.
Incremental: each price update folds the 1-step return into a `RollingMeanStd`
window in O(1); the emitted value is the negative z-score of the latest return
(abnormal up-move → negative → expect reversion down).
"""
from __future__ import annotations

from bot.framework.events import Event
from bot.framework.registry import register
from bot.framework.signals.base import Signal
from bot.framework.state import MarketState, RollingMeanStd


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
