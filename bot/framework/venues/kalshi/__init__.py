# bot/framework/venues/kalshi/
"""Kalshi venue — CFTC-regulated prediction markets (binary event contracts).

Self-contained: RSA-PSS auth (`auth.py`), a thin REST client (`client.py`), a
live data adapter (`adapter.py`), historical candlesticks (`history.py`), and a
scaffold live broker (`broker.py`). Prediction-market quirks (probability prices
in [0,1], YES/NO contracts, resolution/settlement, churning universe) live here,
not in the core.
"""
from bot.framework.venues.kalshi.venue import KalshiVenue
from bot.framework.venues.base import register_venue

register_venue(KalshiVenue())
