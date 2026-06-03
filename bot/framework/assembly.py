# bot/framework/assembly.py
"""Wire a `RunConfig` + specs + sources into an `EventEngine`.

Both entrypoints (live, backtest) build the identical core through here — the
only thing they differ on is which `Source`s they pass. That sameness is the
mode-agnostic guarantee in code form.
"""
from __future__ import annotations

from functools import partial

from bot.framework.allocator import CrossSectionalAllocator
from bot.framework.broker import SimBroker
from bot.framework.config import RunConfig
from bot.framework.engine import EventEngine
from bot.framework.instruments import InstrumentSpec
from bot.framework.recorder import Recorder
from bot.framework.registry import get_signal
from bot.framework.risk import RiskMonitor
from bot.framework.sources import Source
from bot.framework.universe import Universe


def build_engine(
    cfg: RunConfig,
    specs: list[InstrumentSpec],
    sources: list[Source],
    *,
    record: bool = True,
    run_id: str | None = None,
) -> EventEngine:
    universe = Universe(specs)
    spec_map = {s.symbol: s for s in specs}

    signal_cls = get_signal(cfg.signal)
    signal_factory = partial(_make_signal, signal_cls, cfg.signal_window)

    allocator = CrossSectionalAllocator(
        gross_target_frac=cfg.gross_target_frac,
        top_frac=cfg.top_frac,
        bottom_frac=cfg.bottom_frac,
    )
    risk = RiskMonitor(cfg.risk)
    broker = SimBroker(cfg.starting_cash, spec_map)
    recorder = Recorder(run_id=run_id) if record else None

    return EventEngine(
        sources=sources,
        universe=universe,
        signal_factory=signal_factory,
        allocator=allocator,
        risk=risk,
        broker=broker,
        recorder=recorder,
    )


def _make_signal(signal_cls, window, symbol, spec):
    # signals that take a `window` get one; others are constructed plainly
    try:
        return signal_cls(symbol, spec, window=window)
    except TypeError:
        return signal_cls(symbol, spec)
