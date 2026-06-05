# scripts/sweep_sports_fade.py
"""Grid-search the run-reversal fade to find the profitable region (if any).

Fetches the market data ONCE, then runs `run_backtest` across a grid of
entry_drop x reversion_frac x mode (taker/maker) and prints a table ranked by
NET P&L (after costs). This is the fastest way to see where — if anywhere — the
edge survives Kalshi's fees and spread.

    python -m scripts.sweep_sports_fade --n 40
    python -m scripts.sweep_sports_fade --series KXATPMATCH --conviction

Maker rows assume your limit order fills (optimistic upper bound); taker rows are
the conservative, executable case.
"""
from __future__ import annotations

import argparse

from bot.framework.venues.kalshi.client import KalshiClient
from scripts.backtest_sports_fade import discover_tickers, load_events, run_backtest

ENTRY_DROPS = (0.10, 0.12, 0.15, 0.18, 0.22)
REVERSION_FRACS = (0.4, 0.5, 0.7)
MODES = (("taker", 0.01, 0.07), ("maker", 0.0, 0.0))   # (label, half_spread, fee_coef)


def main():
    p = argparse.ArgumentParser(prog="sweep_sports_fade")
    p.add_argument("--n", type=int, default=40)
    p.add_argument("--series", help="comma-separated series (else liquid tennis matches)")
    p.add_argument("--status", default="settled")
    p.add_argument("--env", default="prod")
    p.add_argument("--cash", type=float, default=10_000.0)
    p.add_argument("--contracts", type=int, default=100)
    p.add_argument("--conviction", action="store_true")
    p.add_argument("--stop-drop", type=float, default=0.10)
    p.add_argument("--max-hold", type=int, default=15)
    args = p.parse_args()

    client = KalshiClient(env=args.env)
    tickers = discover_tickers(client, args.n, args.status, args.series)
    if not tickers:
        raise SystemExit("no markets found")
    print(f"loaded {len(tickers)} markets; sweeping {len(ENTRY_DROPS)*len(REVERSION_FRACS)*len(MODES)} configs ...")
    events = load_events(client, tickers)

    rows = []
    for mode, half_spread, fee_coef in MODES:
        for ed in ENTRY_DROPS:
            for rf in REVERSION_FRACS:
                sig = dict(lookback=4, entry_drop=ed, reversion_frac=rf,
                           stop_drop=args.stop_drop, max_hold=args.max_hold)
                r = run_backtest(tickers, events, signal_params=sig, contracts=args.contracts,
                                 scale_by_conviction=args.conviction, half_spread=half_spread,
                                 fee_coefficient=fee_coef, cash=args.cash)
                rows.append((mode, ed, rf, r))

    rows.sort(key=lambda x: x[3]["net"], reverse=True)
    print(f"\n{'mode':6} {'entry_drop':>10} {'rev_frac':>8} {'trades':>7} {'win%':>6} "
          f"{'gross$':>9} {'NET$':>9}")
    print("-" * 60)
    for mode, ed, rf, r in rows:
        print(f"{mode:6} {ed:>10.2f} {rf:>8.2f} {r['n_trades']:>7} {r['win_rate']*100:>5.0f}% "
              f"{r['gross']:>9,.0f} {r['net']:>9,.0f}")
    best = rows[0]
    print(f"\nbest: {best[0]} entry_drop={best[1]} rev_frac={best[2]} -> NET ${best[3]['net']:,.0f}")
    print("(maker rows assume limit fills — optimistic; taker rows are executable)")


if __name__ == "__main__":
    main()
