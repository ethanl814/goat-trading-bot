# bot/framework/allocator.py
"""Allocator / portfolio construction: signal values -> target positions.

Separated from per-name signal logic (principle 5). Two shapes are supported:

  - `CrossSectionalAllocator` (the reference): rank instruments by their
    *already-normalized* signal, go long the top slice / short the bottom slice,
    equal-weight, sized to a gross target. Because it only ever **ranks** signals,
    a flat "X% move" rule is impossible to express here — normalization is
    structural, not optional (principle: "make a flat X% move rule hard to
    express by accident").
  - `ThresholdAllocator`: per-name triggers for signals that are themselves
    standardized (z-score thresholds), for strategies that aren't cross-sectional.

Both respect adapter-declared constraints *generically* via `InstrumentSpec`
(shortability / long-only / per-name caps / contract multiplier) — no asset-class
branching.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from bot.framework.instruments import InstrumentSpec
from bot.framework.state import MarketState


def _capped(spec: InstrumentSpec, qty: float) -> float:
    """Round to lot size and clamp to the per-name cap, preserving sign."""
    qty = spec.round_qty(qty)
    if spec.max_position_qty is not None:
        cap = spec.max_position_qty
        qty = max(-cap, min(cap, qty))
    if not spec.can_short and qty < 0:
        return 0.0
    return qty


class Allocator(ABC):
    @abstractmethod
    def targets(
        self,
        signals: dict[str, float],
        states: dict[str, MarketState],
        specs: dict[str, InstrumentSpec],
        equity: float,
    ) -> dict[str, float]:
        """Map current signal values to target positions (signed qty per name)."""
        raise NotImplementedError


class CrossSectionalAllocator(Allocator):
    def __init__(
        self,
        *,
        gross_target_frac: float = 1.0,
        top_frac: float = 0.2,
        bottom_frac: float = 0.2,
        min_names: int = 2,
    ):
        self.gross_target_frac = gross_target_frac
        self.top_frac = top_frac
        self.bottom_frac = bottom_frac
        self.min_names = min_names

    def targets(self, signals, states, specs, equity):
        # only names with a live signal value and a usable price
        usable = {
            s: v for s, v in signals.items()
            if v is not None and states.get(s) and states[s].price() not in (None, 0)
        }
        if len(usable) < self.min_names:
            return {}

        ranked = sorted(usable, key=lambda s: usable[s])  # ascending signal
        n = len(ranked)
        k_top = max(1, int(n * self.top_frac))
        k_bot = max(1, int(n * self.bottom_frac))

        longs = ranked[-k_top:]                       # highest signal -> long
        shorts = [s for s in ranked[:k_bot]           # lowest signal -> short,
                  if specs[s].can_short]              # if allowed by the adapter
        selected = set(longs) | set(shorts)
        if not selected:
            return {}

        gross_dollars = self.gross_target_frac * equity
        per_name = gross_dollars / len(selected)

        targets: dict[str, float] = {}
        for sym in selected:
            spec, price = specs[sym], states[sym].price()
            unit_value = price * spec.contract_multiplier
            side = 1.0 if sym in longs else -1.0
            targets[sym] = _capped(spec, side * per_name / unit_value)
        return targets


class ThresholdAllocator(Allocator):
    """Per-name triggers on a standardized signal (e.g. |z| > entry). Equal-weight
    fixed notional per triggered name. Kept simple; the cross-sectional allocator
    is the reference path."""

    def __init__(self, *, entry_z: float = 1.0, per_name_frac: float = 0.05):
        self.entry_z = entry_z
        self.per_name_frac = per_name_frac

    def targets(self, signals, states, specs, equity):
        targets: dict[str, float] = {}
        for sym, v in signals.items():
            if v is None or abs(v) < self.entry_z:
                continue
            st = states.get(sym)
            if not st or st.price() in (None, 0):
                continue
            spec = specs[sym]
            unit_value = st.price() * spec.contract_multiplier
            side = 1.0 if v > 0 else -1.0
            targets[sym] = _capped(spec, side * self.per_name_frac * equity / unit_value)
        return targets
