# bot/framework/config.py
"""Run configuration. Credentials stay in the environment (.env via dotenv,
loaded by the Alpaca broker); this holds the knobs an entrypoint needs.

Kept as a plain dataclass with sane defaults so live and backtest entrypoints
share one config surface. Tune here rather than threading kwargs everywhere.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from bot.framework.risk import RiskLimits


@dataclass
class RunConfig:
    signal: str = "reversion"
    signal_window: int = 20

    starting_cash: float = 100_000.0
    decision_interval_seconds: float = 60.0  # throttle for the allocator step

    # cross-sectional allocator
    gross_target_frac: float = 1.0
    top_frac: float = 0.2
    bottom_frac: float = 0.2

    risk: RiskLimits = field(default_factory=RiskLimits)
