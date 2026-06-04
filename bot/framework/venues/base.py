# bot/framework/venues/base.py
"""`Venue` contract + registry.

A venue answers three questions for the launcher, and nothing else:
  - `live_setup(symbols, mode)`     -> (Source, [InstrumentSpec])  for live runs
  - `backtest_setup(symbols, ...)`  -> ([Event], [InstrumentSpec], decision_interval)
  - `make_broker(mode, ...)`        -> Broker  (SimBroker for SIM; live broker otherwise)

The SIM/LIVE broker policy (and the real-money guard) lives here so every venue
inherits it identically — only the venue-specific *live* broker differs.
"""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from datetime import timedelta

from bot.framework.broker import Broker, SimBroker
from bot.framework.events import Event
from bot.framework.instruments import AssetClass, InstrumentSpec
from bot.framework.modes import TradingMode
from bot.framework.sources import Source

_REGISTRY: dict[str, "Venue"] = {}


def register_venue(venue: "Venue") -> "Venue":
    _REGISTRY[venue.name] = venue
    return venue


def get_venue(name: str) -> "Venue":
    if name not in _REGISTRY:
        raise KeyError(f"unknown venue {name!r}; registered: {sorted(_REGISTRY)}")
    return _REGISTRY[name]


class Venue(ABC):
    name: str
    asset_class: AssetClass

    @abstractmethod
    def live_setup(self, symbols: list[str], mode: TradingMode) -> tuple[Source, list[InstrumentSpec]]:
        """Build the live data source and the instrument specs for `symbols`."""
        raise NotImplementedError

    @abstractmethod
    def backtest_setup(self, symbols: list[str], start: str, end: str,
                       timeframe: str) -> tuple[list[Event], list[InstrumentSpec], timedelta]:
        """Load historical events + specs + the decision cadence for a replay."""
        raise NotImplementedError

    # --- broker policy (shared) ---------------------------------------------
    def make_broker(self, mode: TradingMode, spec_map: dict, starting_cash: float) -> Broker:
        if mode is TradingMode.SIM:
            return SimBroker(starting_cash, spec_map)
        if mode is TradingMode.LIVE and os.getenv("ALLOW_LIVE_TRADING", "").lower() != "yes":
            raise RuntimeError(
                "MODE=LIVE but ALLOW_LIVE_TRADING != 'yes'. Refusing to route "
                "real-money orders. Set ALLOW_LIVE_TRADING=yes to confirm.")
        return self._live_broker(mode, spec_map)

    @abstractmethod
    def _live_broker(self, mode: TradingMode, spec_map: dict) -> Broker:
        """Venue-specific broker that routes real orders (paper or live account)."""
        raise NotImplementedError
