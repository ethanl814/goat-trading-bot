# bot/framework/history.py
"""Historical bar loading for backtests — turn real market history into the same
`Bar` event stream the live path produces.

Two sources, one shape:
  - `fetch_alpaca_bars` pulls OHLCV from Alpaca's `get_bars` (the data the live
    adapter would have seen) and normalizes to `Bar` events.
  - `load_bars_csv` (in replay.py) reads a CSV you bring yourself.

`fetch_or_load` caches fetches to `data/` as CSV so you only hit the API once per
(symbols, window, timeframe) — iterate on a signal without re-downloading.
"""
from __future__ import annotations

import csv
import logging
from datetime import datetime
from pathlib import Path

from bot.framework.events import Bar, Event
from bot.framework.replay import load_bars_csv

log = logging.getLogger(__name__)

_TIMEFRAMES = {"1Day": "Day", "1Hour": "Hour", "1Min": "Minute"}


def _timeframe(name: str):
    import alpaca_trade_api as tradeapi
    unit = _TIMEFRAMES.get(name)
    if unit is None:
        raise ValueError(f"unsupported timeframe {name!r}; use one of {list(_TIMEFRAMES)}")
    return getattr(tradeapi.TimeFrame, unit)


def fetch_alpaca_bars(
    symbols: list[str], start: str, end: str, *,
    timeframe: str = "1Day", feed: str | None = None, broker=None,
) -> list[Event]:
    """Fetch OHLCV bars for `symbols` over [start, end] (ISO dates) as Bar events."""
    if broker is None:
        from bot.brokers.alpaca import AlpacaBroker
        broker = AlpacaBroker(paper=True)
    feed = feed or broker.feed
    tf = _timeframe(timeframe)

    events: list[Event] = []
    for sym in symbols:
        try:
            bars = broker.api.get_bars(sym, tf, start=start, end=end, feed=feed)
        except Exception as e:
            log.warning("get_bars(%s) failed: %s", sym, e)
            continue
        for b in bars:
            events.append(Bar(
                instrument=sym, ts=getattr(b, "t", None) or datetime.fromisoformat(start),
                open=float(b.o), high=float(b.h), low=float(b.l),
                close=float(b.c), volume=float(getattr(b, "v", 0) or 0)))
    log.info("fetched %d bars over %s (%s, %s..%s)", len(events), symbols, timeframe, start, end)
    return events


def save_bars_csv(events: list[Event], path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ts", "symbol", "open", "high", "low", "close", "volume"])
        for e in events:
            if isinstance(e, Bar):
                w.writerow([e.ts.isoformat(), e.instrument, e.open, e.high, e.low, e.close, e.volume])


def fetch_or_load(
    symbols: list[str], start: str, end: str, *,
    timeframe: str = "1Day", feed: str | None = None,
    cache_dir: str = "data",
) -> list[Event]:
    """Load bars from a cached CSV if present, else fetch from Alpaca and cache."""
    tag = f"{'-'.join(sorted(symbols))[:40]}_{start}_{end}_{timeframe}"
    cache = Path(cache_dir) / f"bars_{tag}.csv"
    if cache.exists():
        log.info("loading cached bars from %s", cache)
        return load_bars_csv(cache)
    events = fetch_alpaca_bars(symbols, start, end, timeframe=timeframe, feed=feed)
    if events:
        save_bars_csv(events, cache)
    return events
