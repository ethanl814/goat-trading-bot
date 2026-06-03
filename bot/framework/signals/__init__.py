# bot/framework/signals/
"""Signals: the plug-in point. One incremental, stateful instance per instrument.

Adding a signal = subclass `Signal`, implement O(1) `update` + `value`, and
`@register("name")` it. No core changes. See `base.py` and `reversion.py`.
"""
