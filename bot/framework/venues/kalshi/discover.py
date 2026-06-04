# bot/framework/venues/kalshi/discover.py
"""Market discovery + liquidity ranking for Kalshi.

The point: make picking *what to trade/backtest* easy. `get_markets(status="open")`
is dominated by auto-generated sports parlay markets (`KXMVE...`), so naive
browsing is useless. These helpers paginate, filter out the parlay noise, rank by
liquidity, group by series (category), and check candle history — so you can find
a real market and drop its ticker straight into `control.py`.

For backtesting a *thesis*, prefer `status="settled"`: those markets have full
price history AND a known outcome, so the engine's Resolution/settlement gives
true binary-payoff PnL.
"""
from __future__ import annotations

import time

from bot.framework.venues.kalshi.client import KalshiClient, to_float

# Auto-generated multi-leg sports/parlay markets that flood the open feed.
SPORTS_PREFIXES = ("KXMVE",)


def _volume(m: dict) -> float:
    return to_float(m.get("volume_24h_fp")) or to_float(m.get("volume_fp")) or 0.0


def series_of(m: dict) -> str:
    return m.get("series_ticker") or m["ticker"].split("-")[0]


def _is_sports(m: dict) -> bool:
    return m["ticker"].startswith(SPORTS_PREFIXES)


def summarize(m: dict) -> dict:
    return {
        "ticker": m["ticker"],
        "series": series_of(m),
        "title": (m.get("title") or "")[:70],
        "volume": _volume(m),
        "open_interest": to_float(m.get("open_interest_fp")) or 0.0,
        "last": to_float(m.get("last_price_dollars")),
        "yes_bid": to_float(m.get("yes_bid_dollars")),
        "yes_ask": to_float(m.get("yes_ask_dollars")),
        "status": m.get("status"),
        "close_time": m.get("close_time"),
    }


def liquid_markets(client: KalshiClient | None = None, *, n: int = 25,
                   status: str = "open", series_ticker: str | None = None,
                   min_volume: float = 0.0, include_sports: bool = False,
                   query: str | None = None, max_markets: int = 10_000) -> list[dict]:
    """Top `n` markets by liquidity, parlay noise filtered out by default."""
    client = client or KalshiClient()
    q = query.lower() if query else None
    rows: list[dict] = []
    for m in client.iter_markets(status=status, series_ticker=series_ticker, max_markets=max_markets):
        if not include_sports and _is_sports(m):
            continue
        if q and q not in (m.get("title") or "").lower():
            continue
        if _volume(m) < min_volume:
            continue
        rows.append(summarize(m))
    rows.sort(key=lambda r: r["volume"], reverse=True)
    return rows[:n]


def top_series(client: KalshiClient | None = None, *, status: str = "open",
               include_sports: bool = False, n: int = 25,
               max_markets: int = 10_000) -> list[dict]:
    """Series (≈ categories) ranked by total liquidity — discover what's tradeable."""
    client = client or KalshiClient()
    agg: dict[str, dict] = {}
    for m in client.iter_markets(status=status, max_markets=max_markets):
        if not include_sports and _is_sports(m):
            continue
        s = series_of(m)
        a = agg.setdefault(s, {"series": s, "markets": 0, "volume": 0.0})
        a["markets"] += 1
        a["volume"] += _volume(m)
    return sorted(agg.values(), key=lambda a: a["volume"], reverse=True)[:n]


def candle_count(client: KalshiClient | None, ticker: str, *,
                 days: int = 90, period_interval: int = 1440) -> int:
    """How many traded candles a market has in the last `days` — i.e. is it
    backtestable. period_interval in minutes (1 / 60 / 1440)."""
    client = client or KalshiClient()
    end = int(time.time())
    start = end - days * 24 * 3600
    try:
        cs = client.get_candlesticks(ticker, start, end, period_interval).get("candlesticks", [])
    except Exception:
        return 0
    return sum(1 for c in cs if (c.get("price") or {}).get("close") is not None)
