# bot/framework/signals/edge.py
"""Prediction-market reference signal: standardized edge vs a fair value.

This is the *template* for testing a prediction-market theory. A theory is just
a fair-value estimate for a contract; the signal emits the standardized edge
(how far the market price sits from fair, in volatility units), which a
`ThresholdAllocator` turns into a per-name trigger.

`ProbabilityReversion` ships a trivial fair value — a rolling mean of the price —
purely to exercise the pipeline (NOT alpha). To test a real theory, subclass it
and override `fair_value(self, state)` to return YOUR model's probability:

    @register("my_thesis")
    class MyThesis(ProbabilityReversion):
        def fair_value(self, state):
            return my_model_prob(self.instrument, state)   # your edge

Everything else (standardization, triggering, sizing, settlement PnL) is handled
by the framework.
"""
from __future__ import annotations

from bot.framework.events import Event
from bot.framework.instruments import AssetClass
from bot.framework.registry import register
from bot.framework.signals.base import Signal
from bot.framework.state import MarketState, RollingMeanStd


@register("prob_reversion")
class ProbabilityReversion(Signal):
    name = "prob_reversion"
    applies_to = (AssetClass.PREDICTION_MARKET,)

    def __init__(self, instrument, spec, window: int = 30):
        super().__init__(instrument, spec)
        self._prices = RollingMeanStd(window)
        self._price: float | None = None

    def fair_value(self, state: MarketState) -> float | None:
        """Your theory goes here. Default: rolling-mean fair value (plumbing only)."""
        return self._prices.mean() if self._prices.ready else None

    def update(self, state: MarketState, event: Event) -> None:
        p = state.price()
        if p is None or not (0.0 < p < 1.0):
            return
        self._price = p
        self._prices.push(p)

    def value(self) -> float | None:
        if self._price is None:
            return None
        fair = self.fair_value(None)
        if fair is None:
            return None
        sd = self._prices.std()
        if sd <= 0:
            return None
        # positive => market is below fair (cheap YES) => want to buy
        return (fair - self._price) / sd
