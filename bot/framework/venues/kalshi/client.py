# bot/framework/venues/kalshi/client.py
"""Thin authenticated Kalshi REST client (sync `requests`).

Hosts differ between the trade API and the historical/candlestick API, and
between demo and prod — all overridable via env so we can pin whichever the
account's key actually authenticates against:

    KALSHI_ENV            demo | prod         (default demo)
    KALSHI_TRADE_HOST     override trade host
    KALSHI_HISTORICAL_HOST override historical host
    KALSHI_API_KEY_ID, KALSHI_PRIVATE_KEY_PATH

Prices come back as fixed-point dollar strings in [0,1] (e.g. "0.5600"); helpers
return floats. Only market-data + the handful of trading calls the broker needs
are wrapped — add endpoints here rather than calling requests elsewhere.
"""
from __future__ import annotations

import logging
import os

import requests

from bot.framework.venues.kalshi.auth import auth_headers, load_private_key

log = logging.getLogger(__name__)

_API = "/trade-api/v2"

_HOSTS = {
    "demo": {"trade": "https://demo-api.kalshi.co",
             "historical": "https://external-api.demo.kalshi.co"},
    "prod": {"trade": "https://api.elections.kalshi.com",
             "historical": "https://external-api.kalshi.com"},
}


def to_float(v) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


class KalshiClient:
    def __init__(self, env: str | None = None, *, key_id: str | None = None,
                 private_key_path: str | None = None,
                 trade_host: str | None = None, historical_host: str | None = None):
        self.env = (env or os.getenv("KALSHI_ENV", "demo")).lower()
        hosts = _HOSTS.get(self.env, _HOSTS["demo"])
        self.trade_host = trade_host or os.getenv("KALSHI_TRADE_HOST") or hosts["trade"]
        self.historical_host = (historical_host or os.getenv("KALSHI_HISTORICAL_HOST")
                                or hosts["historical"])
        self.key_id = key_id or os.getenv("KALSHI_API_KEY_ID")
        key_path = private_key_path or os.getenv("KALSHI_PRIVATE_KEY_PATH")
        self._key = load_private_key(key_path) if key_path else None
        self._session = requests.Session()

    # --- transport -----------------------------------------------------------
    def _request(self, method: str, host: str, path: str, *, params=None, json=None):
        headers = {"Accept": "application/json"}
        if self.key_id and self._key:
            headers.update(auth_headers(self.key_id, self._key, method, path))
        resp = self._session.request(method, host + path, params=params, json=json,
                                     headers=headers, timeout=20)
        resp.raise_for_status()
        return resp.json() if resp.content else {}

    def _get(self, path, **params):
        params = {k: v for k, v in params.items() if v is not None}
        return self._request("GET", self.trade_host, path, params=params)

    # --- market data ---------------------------------------------------------
    def exchange_status(self):
        return self._request("GET", self.trade_host, f"{_API}/exchange/status")

    def get_markets(self, *, status="open", series_ticker=None, event_ticker=None, limit=100, cursor=None):
        return self._get(f"{_API}/markets", status=status, series_ticker=series_ticker,
                         event_ticker=event_ticker, limit=limit, cursor=cursor)

    def iter_markets(self, *, status="open", series_ticker=None, page_size=1000, max_markets=10_000):
        """Yield markets across pages (follows the response cursor)."""
        cursor, seen = None, 0
        while seen < max_markets:
            resp = self.get_markets(status=status, series_ticker=series_ticker,
                                    limit=page_size, cursor=cursor)
            markets = resp.get("markets", [])
            for m in markets:
                yield m
                seen += 1
            cursor = resp.get("cursor")
            if not cursor or not markets:
                break

    def get_market(self, ticker: str):
        return self._get(f"{_API}/markets/{ticker}").get("market", {})

    def get_orderbook(self, ticker: str, depth: int = 1):
        return self._get(f"{_API}/markets/{ticker}/orderbook", depth=depth)

    def get_candlesticks(self, ticker: str, start_ts: int, end_ts: int, period_interval: int,
                         series_ticker: str | None = None):
        """Candlesticks for a market. period_interval in minutes: 1, 60, 1440.
        Endpoint is series-scoped on the trade host:
        /series/{series}/markets/{ticker}/candlesticks. The series ticker is the
        prefix of the market ticker before the first '-' when not supplied."""
        series = series_ticker or ticker.split("-")[0]
        path = f"{_API}/series/{series}/markets/{ticker}/candlesticks"
        return self._request("GET", self.trade_host, path,
                             params={"start_ts": start_ts, "end_ts": end_ts,
                                     "period_interval": period_interval})

    # --- account / trading (used by the live broker) -------------------------
    def get_balance(self):
        return self._request("GET", self.trade_host, f"{_API}/portfolio/balance")

    def get_positions(self):
        return self._request("GET", self.trade_host, f"{_API}/portfolio/positions")

    def create_order(self, *, ticker: str, side: str, action: str, count: int,
                     order_type: str = "market"):
        body = {"ticker": ticker, "side": side, "action": action,
                "count": int(count), "type": order_type}
        return self._request("POST", self.trade_host, f"{_API}/portfolio/orders", json=body)
