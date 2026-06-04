# bot/framework/venues/
"""Venue plugins — one self-contained package per trading venue / asset class.

A *venue* bundles everything market-specific: how to set up a live data source,
how to load historical bars for backtests, how to declare instrument specs, and
how to build a live broker. The core engine/signals/allocator/risk never import
a venue — the launcher (`bot/run.py`) looks one up by name through the registry
here. Adding a venue = drop a package with a `Venue` subclass and register it.

This is the "trading desk" seam: equities (Alpaca) and prediction markets
(Kalshi) live side by side, share nothing but the `Venue` contract, and can
evolve independently.
"""
from bot.framework.venues.base import Venue, get_venue, register_venue  # noqa: F401

# Import venue packages so they self-register on `import bot.framework.venues`.
from bot.framework.venues import alpaca as _alpaca  # noqa: F401,E402
from bot.framework.venues import kalshi as _kalshi  # noqa: F401,E402
