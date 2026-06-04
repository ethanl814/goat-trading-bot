# bot/framework/venues/kalshi/venue.py
"""KalshiVenue — wires the prediction-market adapter / history / broker in.

Demo (paper) and prod accounts use separate Kalshi keys/hosts; SIM and PAPER use
the demo environment for data, LIVE uses prod. Historical candlesticks for
backtests always come from prod (that's where the archive lives)."""
from __future__ import annotations

from datetime import timedelta

from bot.framework.instruments import AssetClass
from bot.framework.modes import TradingMode
from bot.framework.replay import cached_bars
from bot.framework.venues.base import Venue
from bot.framework.venues.kalshi.adapter import KalshiAdapter, build_spec
from bot.framework.venues.kalshi.client import KalshiClient

_TF_DELTA = {"1Day": timedelta(days=1), "1Hour": timedelta(hours=1), "1Min": timedelta(minutes=1)}


class KalshiVenue(Venue):
    name = "kalshi"
    asset_class = AssetClass.PREDICTION_MARKET

    def live_setup(self, tickers, mode):
        env = "prod" if mode is TradingMode.LIVE else "demo"
        adapter = KalshiAdapter(tickers, client=KalshiClient(env=env))
        return adapter, [build_spec(t) for t in tickers]

    def backtest_setup(self, tickers, start, end, timeframe):
        from bot.framework.venues.kalshi.history import fetch_bars, fetch_resolutions
        client = KalshiClient(env="prod")   # historical archive is on prod
        key = f"kalshi_{'-'.join(sorted(tickers))[:40]}_{start}_{end}_{timeframe}"
        bars = cached_bars("data", key,
                           lambda: fetch_bars(tickers, start, end, timeframe=timeframe, client=client))
        # append settlement events so the engine pays out binary outcomes
        events = bars + fetch_resolutions(tickers, client=client)
        specs = [build_spec(t) for t in tickers]
        return events, specs, _TF_DELTA.get(timeframe, timedelta(days=1))

    def _live_broker(self, mode, spec_map):
        from bot.framework.venues.kalshi.broker import LiveKalshiBroker
        return LiveKalshiBroker(mode, spec_map)
