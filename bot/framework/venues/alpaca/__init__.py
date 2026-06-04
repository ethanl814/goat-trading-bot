# bot/framework/venues/alpaca/
"""Alpaca venue — US equities (the fully-wired reference asset class)."""
from bot.framework.venues.alpaca.venue import AlpacaVenue
from bot.framework.venues.base import register_venue

register_venue(AlpacaVenue())
