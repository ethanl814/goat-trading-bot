# bot/framework/modes.py
"""Trading mode, credential resolution, and the broker factory.

One switch, `TradingMode`, decides how orders are executed and which Alpaca
account/keys are used:

  - SIM   — `SimBroker`, simulated fills. No real order routing. (Default; safe.)
  - PAPER — real orders routed to your Alpaca **paper** account (fake money,
            real order lifecycle).
  - LIVE  — real orders to your Alpaca **live** account. REAL MONEY.

Credentials are resolved per mode from the environment so paper and live keys
never get crossed:

    ALPACA_PAPER_KEY_ID / ALPACA_PAPER_SECRET_KEY      (PAPER + SIM data)
    ALPACA_LIVE_KEY_ID  / ALPACA_LIVE_SECRET_KEY       (LIVE)
    ALPACA_KEY_ID / ALPACA_SECRET_KEY                  (legacy fallback = paper)

LIVE has a hard guard: it refuses to arm unless `ALLOW_LIVE_TRADING=yes` is set,
so you can't accidentally trade real money by flipping one enum.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from enum import Enum

from dotenv import load_dotenv

load_dotenv()  # make credential resolution independent of import order

log = logging.getLogger(__name__)

_PAPER_URL = "https://paper-api.alpaca.markets"
_LIVE_URL = "https://api.alpaca.markets"


class TradingMode(str, Enum):
    SIM = "sim"
    PAPER = "paper"
    LIVE = "live"


@dataclass(frozen=True)
class AlpacaCreds:
    key_id: str | None
    secret_key: str | None
    base_url: str
    feed: str


def resolve_creds(mode: TradingMode) -> AlpacaCreds:
    feed = os.getenv("ALPACA_DATA_FEED", "iex")
    if mode is TradingMode.LIVE:
        return AlpacaCreds(os.getenv("ALPACA_LIVE_KEY_ID"),
                           os.getenv("ALPACA_LIVE_SECRET_KEY"), _LIVE_URL, feed)
    # SIM + PAPER use the paper account (SIM only needs it for market data)
    key = os.getenv("ALPACA_PAPER_KEY_ID") or os.getenv("ALPACA_KEY_ID")
    secret = os.getenv("ALPACA_PAPER_SECRET_KEY") or os.getenv("ALPACA_SECRET_KEY")
    return AlpacaCreds(key, secret, _PAPER_URL, feed)


def make_data_broker(mode: TradingMode):
    """An AlpacaBroker (data wrapper) wired to the right account for `mode`.
    Used by adapters to read market data, even in SIM."""
    from bot.brokers.alpaca import AlpacaBroker
    c = resolve_creds(mode)
    return AlpacaBroker(paper=(mode is not TradingMode.LIVE),
                        key_id=c.key_id, secret_key=c.secret_key,
                        base_url=c.base_url, feed=c.feed)


def make_broker(mode: TradingMode, spec_map: dict, starting_cash: float):
    """Build the execution broker for `mode`. SIM -> SimBroker; PAPER/LIVE ->
    LiveAlpacaBroker (real order routing)."""
    from bot.framework.broker import SimBroker
    if mode is TradingMode.SIM:
        return SimBroker(starting_cash, spec_map)

    if mode is TradingMode.LIVE and os.getenv("ALLOW_LIVE_TRADING", "").lower() != "yes":
        raise RuntimeError(
            "MODE=LIVE is armed but ALLOW_LIVE_TRADING != 'yes'. Refusing to route "
            "real-money orders. Set ALLOW_LIVE_TRADING=yes to confirm.")

    from bot.framework.brokers_live import LiveAlpacaBroker
    log.warning("EXECUTION MODE = %s — orders will be routed to Alpaca (%s).",
                mode.value.upper(), "REAL MONEY" if mode is TradingMode.LIVE else "paper account")
    return LiveAlpacaBroker(mode, spec_map)
