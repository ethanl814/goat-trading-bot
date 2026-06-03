# scripts/analyze.py
"""Turn a recorded equity curve (+ fills) into PnL / Sharpe / max drawdown / turnover.

    python -m scripts.analyze logs/equity_backtest.csv

This is the one place pandas is allowed — it's offline analysis, not the hot path.
Sharpe is annualized with a sqrt-of-periods factor inferred from the median
timestamp spacing (falls back to assuming the bars are the period unit).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

_SECONDS_PER_YEAR = 365 * 24 * 3600


def summarize(equity_path: str, fills_path: str | None = None) -> dict:
    eq = pd.read_csv(equity_path, parse_dates=["ts"])
    if eq.empty:
        print(f"[analyze] {equity_path} is empty — no decisions were recorded.")
        return {}

    eq = eq.sort_values("ts").reset_index(drop=True)
    start, end = eq["equity"].iloc[0], eq["equity"].iloc[-1]
    rets = eq["equity"].pct_change().dropna()

    # annualization factor from median spacing between decision points
    if len(eq) > 2:
        dt = eq["ts"].diff().dt.total_seconds().median()
        periods_per_year = _SECONDS_PER_YEAR / dt if dt and dt > 0 else 252
    else:
        periods_per_year = 252
    sharpe = (rets.mean() / rets.std() * (periods_per_year ** 0.5)) if rets.std() else 0.0

    running_max = eq["equity"].cummax()
    max_dd = ((eq["equity"] - running_max) / running_max).min()

    turnover = None
    if fills_path and Path(fills_path).exists():
        fills = pd.read_csv(fills_path)
        if not fills.empty:
            traded = (fills["qty"].abs() * fills["price"]).sum()
            turnover = traded / eq["equity"].mean()

    summary = {
        "start_equity": round(start, 2),
        "end_equity": round(end, 2),
        "total_pnl": round(end - start, 2),
        "total_return_pct": round((end / start - 1) * 100, 2) if start else 0.0,
        "sharpe_annualized": round(sharpe, 2),
        "max_drawdown_pct": round(max_dd * 100, 2) if pd.notna(max_dd) else 0.0,
        "turnover_x_equity": round(turnover, 2) if turnover is not None else None,
        "decision_points": len(eq),
    }
    print("\n=== backtest/live summary ===")
    for k, v in summary.items():
        print(f"  {k:>20}: {v}")
    return summary


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: python -m scripts.analyze <equity.csv> [fills.csv]")
        raise SystemExit(2)
    equity = sys.argv[1]
    fills = sys.argv[2] if len(sys.argv) > 2 else equity.replace("equity_", "fills_")
    summarize(equity, fills)


if __name__ == "__main__":
    main()
