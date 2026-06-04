# bot/framework/modes.py
"""Trading mode — the single execution switch, shared by all venues.

  - SIM   — SimBroker, simulated fills. No real order routing. (Default; safe.)
  - PAPER — real orders to the venue's paper/demo account (fake money, real flow).
  - LIVE  — real orders to the venue's live account. REAL MONEY.

The SIM/LIVE broker policy and the `ALLOW_LIVE_TRADING` guard live in
`venues/base.py::Venue.make_broker`. Per-venue credentials live in each venue
package (`venues/alpaca/creds.py`, `venues/kalshi/client.py`) so paper/live keys
for different venues never get crossed. `.env` is loaded here so credential
lookups work regardless of import order.
"""
from __future__ import annotations

from enum import Enum

from dotenv import load_dotenv

load_dotenv()


class TradingMode(str, Enum):
    SIM = "sim"
    PAPER = "paper"
    LIVE = "live"
