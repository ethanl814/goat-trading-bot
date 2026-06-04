# bot/framework/venues/alpaca/history.py
"""Historical equities bars from Alpaca -> Bar events (for backtests)."""
from __future__ import annotations

import logging
from datetime import datetime

from bot.framework.events import Bar, Event

log = logging.getLogger(__name__)

_TIMEFRAMES = {"1Day": "Day", "1Hour": "Hour", "1Min": "Minute"}


def _timeframe(name: str):
    import alpaca_trade_api as tradeapi
    unit = _TIMEFRAMES.get(name)
    if unit is None:
        raise ValueError(f"unsupported timeframe {name!r}; use {list(_TIMEFRAMES)}")
    return getattr(tradeapi.TimeFrame, unit)


def fetch_bars(symbols: list[str], start: str, end: str, *,
               timeframe: str = "1Day", broker=None) -> list[Event]:
    if broker is None:
        from bot.brokers.alpaca import AlpacaBroker
        broker = AlpacaBroker(paper=True)
    tf = _timeframe(timeframe)
    events: list[Event] = []
    for sym in symbols:
        try:
            bars = broker.api.get_bars(sym, tf, start=start, end=end, feed=broker.feed)
        except Exception as e:
            log.warning("get_bars(%s) failed: %s", sym, e)
            continue
        for b in bars:
            events.append(Bar(instrument=sym, ts=getattr(b, "t", None) or datetime.fromisoformat(start),
                              open=float(b.o), high=float(b.h), low=float(b.l),
                              close=float(b.c), volume=float(getattr(b, "v", 0) or 0)))
    log.info("fetched %d Alpaca bars over %s (%s, %s..%s)", len(events), symbols, timeframe, start, end)
    return events
