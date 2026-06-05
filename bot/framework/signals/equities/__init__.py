# bot/framework/signals/equities/
"""EQUITIES DESK — signals for stock markets (Alpaca venue).

Signals here read a continuous price series. Drop a `Signal` subclass in this
folder and `@register(...)` it; the registry discovers it automatically.
"""
