# bot/framework/universe.py
"""The tradeable set — and its churn.

For perpetual instruments (equities, crypto) the universe is mostly static. For
expiring/resolving ones (futures, prediction markets) it *churns*: contracts
list and later resolve/expire and leave. The engine calls `remove` when a
`Resolution` arrives, so signal/state for a dead instrument is dropped and the
allocator stops targeting it. New listings call `add`.

Universe selection/filtering (liquidity floors, exclusions) is part of strategy
definition, so it lives here rather than being bolted on elsewhere. The filter
is a simple predicate to keep it asset-class-agnostic.
"""
from __future__ import annotations

import logging
from typing import Callable, Iterable

from bot.framework.instruments import InstrumentSpec

log = logging.getLogger(__name__)


class Universe:
    def __init__(
        self,
        specs: Iterable[InstrumentSpec],
        *,
        exclude: Iterable[str] = (),
        keep: Callable[[InstrumentSpec], bool] | None = None,
    ):
        excl = set(exclude)
        self._specs: dict[str, InstrumentSpec] = {
            s.symbol: s for s in specs
            if s.symbol not in excl and (keep is None or keep(s))
        }

    def symbols(self) -> list[str]:
        return list(self._specs)

    def active(self) -> list[InstrumentSpec]:
        return list(self._specs.values())

    def spec(self, symbol: str) -> InstrumentSpec | None:
        return self._specs.get(symbol)

    def __contains__(self, symbol: str) -> bool:
        return symbol in self._specs

    def add(self, spec: InstrumentSpec) -> None:
        if spec.symbol not in self._specs:
            self._specs[spec.symbol] = spec
            log.info("universe + %s", spec.symbol)

    def remove(self, symbol: str) -> InstrumentSpec | None:
        spec = self._specs.pop(symbol, None)
        if spec is not None:
            log.info("universe - %s", symbol)
        return spec
