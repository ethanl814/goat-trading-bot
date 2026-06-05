# bot/framework/signals/prediction_markets/edge.py
# ============================================================================
# STRATEGY CARD
#   name      : prob_reversion     desk: prediction_markets   status: TEMPLATE
#   thesis    : (yours goes here) market price deviates from a fair value and
#               reverts toward it
#   signal    : standardized edge = (fair_value - price) / vol; positive => the
#               market underprices YES => buy
#   entry/exit: per-name trigger via the `threshold` allocator (enter when the
#               edge z-score exceeds entry_z; exit when it decays)
#   risk      : book-level (RiskMonitor) + long-only/cap from the InstrumentSpec;
#               no per-name stop here (add one in a subclass if needed)
#   costs     : Kalshi fees + spread apply — see the sports-fade card for how
#               costs dominate small edges
# ============================================================================
"""Prediction-market thesis TEMPLATE. Override `fair_value` with your model.

The shipped `fair_value` (rolling mean of price) is plumbing only. To test a real
theory, subclass and return YOUR probability estimate:

    @register("my_thesis")
    class MyThesis(ProbabilityReversion):
        def fair_value(self, state):
            return my_model_prob(self.instrument, state)
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
