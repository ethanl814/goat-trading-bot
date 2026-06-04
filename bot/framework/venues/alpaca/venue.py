# bot/framework/venues/alpaca/venue.py
"""AlpacaVenue — wires the equities adapter / history / broker into the launcher."""
from __future__ import annotations

from datetime import timedelta

from bot.framework.events import Event
from bot.framework.instruments import AssetClass, InstrumentSpec, PriceKind
from bot.framework.modes import TradingMode
from bot.framework.replay import cached_bars
from bot.framework.sources import Source
from bot.framework.venues.alpaca.adapter import EquitiesAlpacaAdapter
from bot.framework.venues.alpaca.creds import data_broker
from bot.framework.venues.base import Venue

_TF_DELTA = {"1Day": timedelta(days=1), "1Hour": timedelta(hours=1), "1Min": timedelta(minutes=1)}


class AlpacaVenue(Venue):
    name = "alpaca"
    asset_class = AssetClass.EQUITY

    def live_setup(self, symbols, mode):
        adapter = EquitiesAlpacaAdapter(symbols, subscribe=("trades", "quotes"),
                                        broker=data_broker(mode))
        return adapter, adapter.build_specs(symbols)

    def backtest_setup(self, symbols, start, end, timeframe):
        from bot.framework.venues.alpaca.history import fetch_bars
        key = f"alpaca_{'-'.join(sorted(symbols))[:40]}_{start}_{end}_{timeframe}"
        events = cached_bars("data", key, lambda: fetch_bars(symbols, start, end, timeframe=timeframe))
        specs = [InstrumentSpec(symbol=s, asset_class=AssetClass.EQUITY,
                                price_kind=PriceKind.CONTINUOUS, slippage_bps=2.0)
                 for s in symbols]
        return events, specs, _TF_DELTA.get(timeframe, timedelta(days=1))

    def _live_broker(self, mode, spec_map):
        from bot.framework.venues.alpaca.broker import LiveAlpacaBroker
        return LiveAlpacaBroker(mode, spec_map)
