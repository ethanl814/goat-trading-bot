# scripts/kalshi_discover.py
"""Browse Kalshi markets to pick tickers for control.py.

    python -m scripts.kalshi_discover                       # top liquid OPEN markets
    python -m scripts.kalshi_discover --status settled       # settled markets (best for backtests)
    python -m scripts.kalshi_discover --series KXBTCD        # within one series
    python -m scripts.kalshi_discover --query fed --n 30      # title contains "fed"
    python -m scripts.kalshi_discover --series-list           # liquid SERIES (categories)
    python -m scripts.kalshi_discover --check TICKER          # candle history for a ticker
    python -m scripts.kalshi_discover --env demo              # demo instead of prod

Prints a table plus a ready-to-paste `symbols=[...]` snippet for control.py.
Settled markets have full price history + a known outcome → ideal for testing a
thesis end-to-end (the engine adds the binary-payoff settlement).
"""
from __future__ import annotations

import argparse

from bot.framework.venues.kalshi.client import KalshiClient
from bot.framework.venues.kalshi.discover import (candle_count, liquid_markets,
                                                  top_series)


def _fmt(v, width, prec=None):
    if v is None:
        return "-".ljust(width)
    s = f"{v:.{prec}f}" if prec is not None else str(v)
    return s[:width].ljust(width)


def main() -> None:
    p = argparse.ArgumentParser(prog="kalshi_discover")
    p.add_argument("--status", default="open", help="open | settled | closed | unopened")
    p.add_argument("--series", help="restrict to one series ticker")
    p.add_argument("--query", help="title substring filter")
    p.add_argument("--n", type=int, default=25)
    p.add_argument("--min-volume", type=float, default=0.0)
    p.add_argument("--include-sports", action="store_true", help="include KXMVE parlay markets")
    p.add_argument("--series-list", action="store_true", help="list liquid series instead of markets")
    p.add_argument("--check", help="report candle history count for a single ticker")
    p.add_argument("--env", default=None, help="demo | prod (default: KALSHI_ENV/.env)")
    args = p.parse_args()

    client = KalshiClient(env=args.env)

    if args.check:
        for period, label in ((1440, "1d"), (60, "1h"), (1, "1m")):
            n = candle_count(client, args.check, period_interval=period, days=90)
            print(f"{args.check}: {n} traded {label} candles in last 90d")
        return

    if args.series_list:
        rows = top_series(client, status=args.status, include_sports=args.include_sports, n=args.n)
        print(f"\n{'SERIES':<28} {'MARKETS':>8} {'VOLUME':>14}")
        for r in rows:
            print(f"{_fmt(r['series'],28)} {r['markets']:>8} {r['volume']:>14,.0f}")
        print("\nThen drill in:  python -m scripts.kalshi_discover --series <SERIES>")
        return

    rows = liquid_markets(client, n=args.n, status=args.status, series_ticker=args.series,
                          min_volume=args.min_volume, include_sports=args.include_sports,
                          query=args.query)
    if not rows:
        print("no markets matched — try --include-sports, a --series, or --status settled")
        return

    print(f"\n{'TICKER':<42} {'VOL':>10} {'LAST':>6} {'BID':>5} {'ASK':>5}  TITLE")
    for r in rows:
        print(f"{_fmt(r['ticker'],42)} {r['volume']:>10,.0f} "
              f"{_fmt(r['last'],6,2)} {_fmt(r['yes_bid'],5,2)} {_fmt(r['yes_ask'],5,2)}  {r['title']}")

    print("\n# paste into a StrategySpec in control.py:")
    print("symbols=[")
    for r in rows[:10]:
        print(f'    "{r["ticker"]}",  # {r["title"]}')
    print("]")


if __name__ == "__main__":
    main()
