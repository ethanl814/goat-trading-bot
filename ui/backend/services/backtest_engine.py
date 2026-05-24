# Backtest engine: replay historical data through a strategy, report P&L/metrics.
from typing import Any


def run(strategy: Any, start: str, end: str, symbols: list[str]) -> dict:
    raise NotImplementedError
