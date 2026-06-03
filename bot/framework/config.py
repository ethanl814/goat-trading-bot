# bot/framework/config.py
"""Run configuration.

`RunConfig` holds book-level settings shared by every strategy (starting cash,
decision cadence, risk limits). `StrategySpec` is one *toggleable* strategy: a
signal + its params + a universe + how to size it. The control panel (`control.py`)
holds a list of these and flips `enabled` to turn strategies on/off.

Credentials never live here — they're resolved per `TradingMode` from the
environment in `modes.py`.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from bot.framework.risk import RiskLimits


@dataclass
class RunConfig:
    default_signal: str = "reversion"        # used when no StrategySpec list is given
    starting_cash: float = 100_000.0
    decision_interval_seconds: float = 60.0  # throttle for the allocator step
    risk: RiskLimits = field(default_factory=RiskLimits)


@dataclass
class StrategySpec:
    name: str
    signal: str = "reversion"
    enabled: bool = True
    symbols: list[str] = field(default_factory=list)
    signal_params: dict = field(default_factory=dict)   # e.g. {"window": 20}

    # cross-sectional allocator knobs
    gross_target_frac: float = 1.0
    top_frac: float = 0.2
    bottom_frac: float = 0.2
    capital_frac: float = 1.0      # share of book equity this strategy sizes against
