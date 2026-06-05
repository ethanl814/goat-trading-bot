# bot/framework/signals/prediction_markets/
"""PREDICTION-MARKETS DESK — signals for binary event contracts (Kalshi venue).

Prices are probabilities in [0,1] that resolve to 0 or 1. Signals here usually
express a view on an event's true probability (an edge vs the market price), and
pair with the `threshold` or `event_fade` allocators. Drop a `Signal` subclass
here and `@register(...)` it.
"""
