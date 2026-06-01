# bot/core/registry.py
"""Auto-discovery of strategies.

Walks the `bot.strategies` package (and every sub-package: regular,
blockchain_crypto, commodities, prediction_markets, …), imports each module,
and instantiates every concrete `Strategy` subclass it finds. Adding a new
strategy is therefore just: drop a file defining a `Strategy` subclass into a
strategies sub-package. No edits to the engine or main.py required.
"""
import importlib
import inspect
import logging
import pkgutil

import bot.strategies as strategies_pkg
from bot.core.strategy import Strategy

log = logging.getLogger(__name__)


def _iter_modules(package):
    """Recursively import and yield every module under a package."""
    for info in pkgutil.walk_packages(package.__path__, package.__name__ + "."):
        if info.ispkg:
            continue
        try:
            yield importlib.import_module(info.name)
        except Exception as e:
            log.error("could not import strategy module %s: %s", info.name, e)


def discover_strategies(disabled: tuple[str, ...] = ()) -> list[Strategy]:
    found: dict[str, Strategy] = {}
    for module in _iter_modules(strategies_pkg):
        for _, obj in inspect.getmembers(module, inspect.isclass):
            # Only classes *defined here* (not Strategy itself or imported ones),
            # and only concrete ones.
            if (issubclass(obj, Strategy) and obj is not Strategy
                    and not inspect.isabstract(obj)
                    and obj.__module__ == module.__name__):
                inst = obj()
                if inst.name in disabled:
                    inst.enabled = False
                found[inst.name] = inst
    return list(found.values())
