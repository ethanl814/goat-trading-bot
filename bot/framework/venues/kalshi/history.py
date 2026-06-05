# bot/framework/venues/kalshi/history.py
"""Historical Kalshi candlesticks -> Bar events (for backtesting theories).

Maps Kalshi's candlestick endpoint (1/60/1440-minute intervals) onto the
framework's `Bar` model. Close price preference: traded `price.close`, falling
back to the yes bid/ask mid when no trade occurred in the interval. Prices are
already probabilities in [0,1]. Pair a replay of these bars with a final
`Resolution` (the engine adds settlement) to get true binary-payoff PnL.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from bot.framework.events import Bar, Event, Resolution
from bot.framework.venues.kalshi.client import KalshiClient, to_float

_SETTLED = {"settled", "finalized", "determined"}

log = logging.getLogger(__name__)

_PERIOD = {"1Day": 1440, "1Hour": 60, "1Min": 1}


def _unix(date_str: str) -> int:
    dt = datetime.fromisoformat(date_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


def _field(obj: dict, key: str) -> float | None:
    """Kalshi candle OHLC fields are suffixed `_dollars` (e.g. `close_dollars`);
    accept the bare key too for forward-compat."""
    return to_float(obj.get(f"{key}_dollars", obj.get(key)))


def _ohlc(candle: dict) -> tuple[float, float, float, float] | None:
    """Pull (open, high, low, close) from a candle, preferring traded price and
    falling back to the yes bid/ask mid."""
    price = candle.get("price") or {}
    o, h, l, c = (_field(price, k) for k in ("open", "high", "low", "close"))
    if c is None:  # no trades this interval -> use yes bid/ask midpoints
        bid, ask = candle.get("yes_bid") or {}, candle.get("yes_ask") or {}
        def mid(k):
            b, a = _field(bid, k), _field(ask, k)
            return (b + a) / 2 if b is not None and a is not None else None
        o, h, l, c = mid("open"), mid("high"), mid("low"), mid("close")
    if c is None:
        return None
    o = o if o is not None else c
    h = h if h is not None else c
    l = l if l is not None else c
    return o, h, l, c


def fetch_bars(tickers: list[str], start: str, end: str, *,
               timeframe: str = "1Day", client: KalshiClient | None = None) -> list[Event]:
    client = client or KalshiClient()
    period = _PERIOD.get(timeframe)
    if period is None:
        raise ValueError(f"unsupported timeframe {timeframe!r}; use {list(_PERIOD)}")
    start_ts, end_ts = _unix(start), _unix(end)

    events: list[Event] = []
    for ticker in tickers:
        try:
            data = client.get_candlesticks(ticker, start_ts, end_ts, period)
        except Exception as e:
            log.warning("candlesticks(%s) failed: %s", ticker, e)
            continue
        for candle in data.get("candlesticks", []):
            ohlc = _ohlc(candle)
            if ohlc is None:
                continue
            o, h, l, c = ohlc
            ts = datetime.fromtimestamp(int(candle["end_period_ts"]), tz=timezone.utc)
            events.append(Bar(instrument=ticker, ts=ts, open=o, high=h, low=l, close=c,
                              volume=to_float(candle.get("volume_fp") or candle.get("volume")) or 0.0))
    log.info("fetched %d Kalshi candles over %s (%s, %s..%s)", len(events), tickers, timeframe, start, end)
    return events


def _parse_ts(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def fetch_game_window(tickers: list[str], *, client: KalshiClient | None = None,
                      lookback_hours: int = 24, period_interval: int = 1) -> list[Event]:
    """Minute-level bars + a settlement for each single-event market (a game/match).

    Single-game markets live < a day, and Kalshi range-limits minute candles, so
    we fetch a window ending at each market's close (read from the market object)
    rather than a fixed calendar range. This is the data path for the in-game
    fade backtest. Returns Bars (intra-game price path) + a final Resolution.
    """
    client = client or KalshiClient()
    events: list[Event] = []
    for ticker in tickers:
        try:
            m = client.get_market(ticker)
        except Exception as e:
            log.warning("get_market(%s) failed: %s", ticker, e)
            continue
        close_dt = _parse_ts(m.get("close_time") or m.get("expiration_time")) or datetime.now(timezone.utc)
        end_ts = int(close_dt.timestamp())
        start_ts = end_ts - lookback_hours * 3600
        try:
            data = client.get_candlesticks(ticker, start_ts, end_ts, period_interval)
        except Exception as e:
            log.warning("candlesticks(%s) failed: %s", ticker, e)
            continue
        n_before = len(events)
        for candle in data.get("candlesticks", []):
            ohlc = _ohlc(candle)
            if ohlc is None:
                continue
            o, h, l, c = ohlc
            ts = datetime.fromtimestamp(int(candle["end_period_ts"]), tz=timezone.utc)
            events.append(Bar(instrument=ticker, ts=ts, open=o, high=h, low=l, close=c,
                              volume=to_float(candle.get("volume_fp")) or 0.0))
        if (m.get("status") or "").lower() in _SETTLED:
            value = 1.0 if (m.get("result") or "").lower() == "yes" else 0.0
            events.append(Resolution(instrument=ticker, value=value,
                                     ts=close_dt + timedelta(minutes=1)))
        log.info("  %s: %d bars + %s", ticker, len(events) - n_before - 1,
                 m.get("result") or m.get("status"))
    return events


def fetch_resolutions(tickers: list[str], *, client: KalshiClient | None = None) -> list[Event]:
    """For any settled markets, a `Resolution` event (YES->1.0, NO->0.0) timed at
    the market's close. Appending these to a backtest replay makes the engine
    settle open positions at the true outcome — real binary-payoff PnL."""
    client = client or KalshiClient()
    out: list[Event] = []
    for t in tickers:
        try:
            m = client.get_market(t)
        except Exception as e:
            log.warning("get_market(%s) failed: %s", t, e)
            continue
        if (m.get("status") or "").lower() not in _SETTLED:
            continue
        value = 1.0 if (m.get("result") or "").lower() == "yes" else 0.0
        ts_raw = m.get("close_time") or m.get("expiration_time")
        try:
            ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00")) if ts_raw else datetime.now(timezone.utc)
        except Exception:
            ts = datetime.now(timezone.utc)
        out.append(Resolution(instrument=t, value=value, ts=ts))
    return out
