# bot/framework/adapters/base.py
"""`MarketAdapter`: a `Source` that also describes its instruments and calendar.

An adapter has a dual role:
  1. **describe** — `build_specs(symbols)` returns `InstrumentSpec`s the universe
     and SimBroker consume (tick/lot/fees/constraints/lifecycle). This is the
     static half of the asset-class abstraction.
  2. **stream** — inherited `Source.run(emit, stop)` pushes normalized events
     (Trade/Quote/Bar/Resolution) for its instruments. This is the dynamic half.

`is_open(now)` exposes the trading calendar as adapter-supplied state so the core
treats "open/closed/halted" generically (24/7 crypto vs session-hours equities
vs event-driven prediction markets) without branching on asset class.
"""
from __future__ import annotations

from abc import abstractmethod
from datetime import datetime

from bot.framework.instruments import AssetClass, InstrumentSpec
from bot.framework.sources import Source


class MarketAdapter(Source):
    asset_class: AssetClass

    @abstractmethod
    def build_specs(self, symbols: list[str]) -> list[InstrumentSpec]:
        """Construct the InstrumentSpecs for these symbols in this asset class."""
        raise NotImplementedError

    def is_open(self, now: datetime | None = None) -> bool:
        """Whether the market is currently tradeable. Default: always open
        (correct for 24/7 crypto; equities/futures adapters override)."""
        return True
