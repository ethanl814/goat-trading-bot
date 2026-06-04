# bot/framework/venues/alpaca/creds.py
"""Alpaca credential resolution per TradingMode.

    ALPACA_PAPER_KEY_ID / ALPACA_PAPER_SECRET_KEY    (PAPER + SIM data)
    ALPACA_LIVE_KEY_ID  / ALPACA_LIVE_SECRET_KEY     (LIVE)
    ALPACA_KEY_ID / ALPACA_SECRET_KEY                (legacy fallback = paper)
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from bot.framework.modes import TradingMode

_PAPER_URL = "https://paper-api.alpaca.markets"
_LIVE_URL = "https://api.alpaca.markets"


@dataclass(frozen=True)
class AlpacaCreds:
    key_id: str | None
    secret_key: str | None
    base_url: str
    feed: str


def resolve(mode: TradingMode) -> AlpacaCreds:
    feed = os.getenv("ALPACA_DATA_FEED", "iex")
    if mode is TradingMode.LIVE:
        return AlpacaCreds(os.getenv("ALPACA_LIVE_KEY_ID"),
                           os.getenv("ALPACA_LIVE_SECRET_KEY"), _LIVE_URL, feed)
    key = os.getenv("ALPACA_PAPER_KEY_ID") or os.getenv("ALPACA_KEY_ID")
    secret = os.getenv("ALPACA_PAPER_SECRET_KEY") or os.getenv("ALPACA_SECRET_KEY")
    return AlpacaCreds(key, secret, _PAPER_URL, feed)


def data_broker(mode: TradingMode):
    """An AlpacaBroker (data wrapper) wired to the right account for `mode`."""
    from bot.brokers.alpaca import AlpacaBroker
    c = resolve(mode)
    return AlpacaBroker(paper=(mode is not TradingMode.LIVE),
                        key_id=c.key_id, secret_key=c.secret_key,
                        base_url=c.base_url, feed=c.feed)
