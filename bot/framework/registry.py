# bot/framework/registry.py
"""Signal registry — adding a signal is one subclass + one decorator.

    @register("reversion")
    class ShortWindowReversion(Signal): ...

Entrypoints then look signals up by name (from config) without importing the
class directly. `discover_signals()` walks the signals package so every module
that defines a registered signal is imported and self-registers.
"""
from __future__ import annotations

import importlib
import logging
import pkgutil
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from bot.framework.signals.base import Signal

log = logging.getLogger(__name__)

_REGISTRY: dict[str, type] = {}


def register(name: str) -> Callable[[type], type]:
    def deco(cls: type) -> type:
        if name in _REGISTRY and _REGISTRY[name] is not cls:
            log.warning("signal name %r already registered; overwriting", name)
        _REGISTRY[name] = cls
        return cls
    return deco


def discover_signals() -> dict[str, type]:
    """Import every module under bot.framework.signals so they self-register."""
    import bot.framework.signals as pkg
    for info in pkgutil.walk_packages(pkg.__path__, pkg.__name__ + "."):
        try:
            importlib.import_module(info.name)
        except Exception as e:  # a broken signal module shouldn't kill discovery
            log.error("could not import signal module %s: %s", info.name, e)
    return dict(_REGISTRY)


def get_signal(name: str) -> type:
    if not _REGISTRY:
        discover_signals()
    if name not in _REGISTRY:
        raise KeyError(f"unknown signal {name!r}; registered: {sorted(_REGISTRY)}")
    return _REGISTRY[name]
