# bot/framework/replay.py
"""Backtest replay `Source` — feeds stored bar/trade data through the SAME core.

Historical L2 book data is scarce/expensive, so the replay model is built around
**bars and trades**, the granularity that's cheap and broadly available. Both
fit under the one event model: a `Bar` updates state to its close; a `Trade`
updates last. Book-based signals can only be validated live, but anything that
reads `MarketState.price()` (the reference signal included) backtests here.

The source interleaves `Clock` events on the *data's* timeline at a fixed
simulated cadence, so the throttled decision step runs deterministically without
any wall-clock sleeping — making backtests fast and reproducible.

`generate_synthetic_bars` lets the backtest entrypoint and tests run end-to-end
out of the box with no data files or credentials.
"""
from __future__ import annotations

import asyncio
import csv
import logging
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

from bot.framework.events import Bar, Clock, Event, Trade
from bot.framework.sources import Emit, Source

log = logging.getLogger(__name__)


class ReplaySource(Source):
    name = "replay"

    def __init__(self, events: list[Event], *, decision_interval: timedelta):
        self.events = sorted(events, key=lambda e: e.ts)
        self.decision_interval = decision_interval

    async def run(self, emit: Emit, stop: asyncio.Event) -> None:
        if not self.events:
            return
        next_decision = self.events[0].ts
        for event in self.events:
            if stop.is_set():
                return
            # emit any decision ticks that fall at/before this event's time
            while event.ts >= next_decision:
                await emit(Clock(ts=next_decision))
                next_decision = next_decision + self.decision_interval
            await emit(event)
        await emit(Clock(ts=self.events[-1].ts))  # final decision on last state


def generate_synthetic_bars(
    symbols: list[str], *, n: int = 500, seed: int = 7,
    start_price: float = 100.0, vol: float = 0.01,
    interval: timedelta = timedelta(minutes=1),
) -> list[Event]:
    """Independent geometric random walks — plumbing exercise data, not a market."""
    rng = random.Random(seed)
    t0 = datetime.now(timezone.utc) - n * interval
    events: list[Event] = []
    for i, sym in enumerate(symbols):
        price = start_price * (1 + 0.1 * i)  # stagger so cross-section has spread
        for k in range(n):
            ret = rng.gauss(0, vol)
            new = max(0.01, price * (1 + ret))
            o, c = price, new
            hi, lo = max(o, c) * (1 + abs(rng.gauss(0, vol / 2))), min(o, c) * (1 - abs(rng.gauss(0, vol / 2)))
            events.append(Bar(instrument=sym, ts=t0 + k * interval,
                              open=o, high=hi, low=lo, close=c,
                              volume=rng.uniform(1e3, 1e5)))
            price = new
    return events


def load_bars_csv(path: str | Path) -> list[Event]:
    """Load bars from a CSV with columns: ts,symbol,open,high,low,close,volume.
    `ts` is ISO-8601. Trades (ts,symbol,price[,size]) are also accepted if the
    file has a `price` column instead of OHLC."""
    events: list[Event] = []
    with Path(path).open(newline="") as f:
        reader = csv.DictReader(f)
        cols = set(reader.fieldnames or [])
        is_trade = "price" in cols and "close" not in cols
        for row in reader:
            ts = datetime.fromisoformat(row["ts"])
            sym = row["symbol"]
            if is_trade:
                events.append(Trade(instrument=sym, ts=ts, price=float(row["price"]),
                                    size=float(row.get("size") or 0)))
            else:
                events.append(Bar(instrument=sym, ts=ts,
                                  open=float(row["open"]), high=float(row["high"]),
                                  low=float(row["low"]), close=float(row["close"]),
                                  volume=float(row.get("volume") or 0)))
    return events
