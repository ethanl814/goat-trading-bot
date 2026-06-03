# bot/framework/risk.py
"""Book-level RiskMonitor — independent of signal logic.

Operates on *aggregate* exposure, computed across all targets/positions, and is
the only component allowed to override the allocator's intent. It:

  - scales targets down to respect gross / net exposure caps and per-asset-class
    gross caps (all expressed as fractions of equity, generically per spec);
  - tracks peak equity and trips a **kill switch** on a drawdown breach — once
    tripped, `gate` returns an all-flat target so the engine unwinds the book,
    and the monitor stays halted (no new risk) until manually reset.

No asset-class branching: caps are keyed by the `AssetClass` enum carried on the
spec, so a new class is covered the moment its adapter emits specs.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from bot.framework.instruments import AssetClass, InstrumentSpec
from bot.framework.state import MarketState

log = logging.getLogger(__name__)


@dataclass
class RiskLimits:
    gross_cap_frac: float = 1.5          # |long| + |short| <= 1.5x equity
    net_cap_frac: float = 1.0            # |long - short| <= 1.0x equity
    max_drawdown_frac: float = 0.20      # trip kill switch at 20% off peak
    per_class_gross_frac: dict[AssetClass, float] = field(default_factory=dict)


class RiskMonitor:
    def __init__(self, limits: RiskLimits | None = None):
        self.limits = limits or RiskLimits()
        self.peak_equity: float | None = None
        self.halted = False

    def check_drawdown(self, equity: float) -> bool:
        """Update peak; return True (and halt) if drawdown breaches the limit."""
        if self.peak_equity is None or equity > self.peak_equity:
            self.peak_equity = equity
        if self.peak_equity and self.peak_equity > 0:
            dd = (self.peak_equity - equity) / self.peak_equity
            if dd >= self.limits.max_drawdown_frac and not self.halted:
                self.halted = True
                log.warning("KILL SWITCH: drawdown %.1f%% >= %.1f%% — flattening & halting",
                            dd * 100, self.limits.max_drawdown_frac * 100)
        return self.halted

    def gate(self, targets, states, specs, equity) -> dict[str, float]:
        """Adjust target positions to respect caps. Returns the approved targets."""
        if self.halted:
            return {s: 0.0 for s in targets}  # flatten everything
        if equity <= 0 or not targets:
            return targets

        def notional(sym, qty):
            st = states.get(sym)
            price = st.price() if st else None
            return abs(qty) * (price or 0) * specs[sym].contract_multiplier

        # 1) per-asset-class gross caps
        for ac, frac in self.limits.per_class_gross_frac.items():
            members = [s for s in targets if specs[s].asset_class == ac]
            gross = sum(notional(s, targets[s]) for s in members)
            cap = frac * equity
            if gross > cap > 0:
                scale = cap / gross
                for s in members:
                    targets[s] *= scale

        # 2) book gross cap
        gross = sum(notional(s, q) for s, q in targets.items())
        cap = self.limits.gross_cap_frac * equity
        if gross > cap > 0:
            scale = cap / gross
            targets = {s: q * scale for s, q in targets.items()}

        # 3) book net cap (signed exposure)
        def signed(sym, qty):
            st = states.get(sym)
            price = st.price() if st else None
            sign = 1 if qty >= 0 else -1
            return sign * abs(qty) * (price or 0) * specs[sym].contract_multiplier

        net = sum(signed(s, q) for s, q in targets.items())
        net_cap = self.limits.net_cap_frac * equity
        if abs(net) > net_cap > 0:
            scale = net_cap / abs(net)
            targets = {s: q * scale for s, q in targets.items()}

        return {s: specs[s].round_qty(q) for s, q in targets.items()}
