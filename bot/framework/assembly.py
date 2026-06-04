# bot/framework/assembly.py
"""Wire a `RunConfig` + strategy specs + sources into an `EventEngine`.

Both entrypoints build the identical core through here — they differ only in the
`Source`s they pass (live adapter vs replay) and the broker (`SimBroker` vs
`LiveAlpacaBroker`). That sameness is the mode-agnostic guarantee in code form.

If no `strategies` list is given, a single default strategy (the config's
`default_signal` over all supplied instruments) is built — keeps simple/test
usage a one-liner.
"""
from __future__ import annotations

from bot.framework.allocator import CrossSectionalAllocator, ThresholdAllocator
from bot.framework.broker import Broker, SimBroker
from bot.framework.config import RunConfig, StrategySpec
from bot.framework.engine import EventEngine
from bot.framework.instruments import InstrumentSpec
from bot.framework.recorder import Recorder
from bot.framework.registry import get_signal
from bot.framework.risk import RiskMonitor
from bot.framework.sources import Source
from bot.framework.strategy import StrategyRunner
from bot.framework.universe import Universe


def build_engine(
    cfg: RunConfig,
    specs: list[InstrumentSpec],
    sources: list[Source],
    *,
    strategies: list[StrategySpec] | None = None,
    broker: Broker | None = None,
    record: bool = True,
    run_id: str | None = None,
) -> EventEngine:
    universe = Universe(specs)
    spec_map = {s.symbol: s for s in specs}

    if strategies is None:
        strategies = [StrategySpec(name="default", signal=cfg.default_signal,
                                   symbols=list(spec_map))]

    runners: list[StrategyRunner] = []
    for sspec in strategies:
        if not sspec.enabled:
            continue
        signal_cls = get_signal(sspec.signal)
        syms = sspec.symbols or list(spec_map)
        signals = {s: signal_cls(s, spec_map[s], **sspec.signal_params)
                   for s in syms if s in spec_map}
        runners.append(StrategyRunner(sspec.name, signals, _make_allocator(sspec),
                                      capital_frac=sspec.capital_frac))

    risk = RiskMonitor(cfg.risk)
    broker = broker or SimBroker(cfg.starting_cash, spec_map)
    recorder = Recorder(run_id=run_id) if record else None

    return EventEngine(
        sources=sources,
        universe=universe,
        strategies=runners,
        risk=risk,
        broker=broker,
        recorder=recorder,
    )


def _make_allocator(sspec: StrategySpec):
    if sspec.allocator == "threshold":
        return ThresholdAllocator(entry_z=sspec.entry_z, per_name_frac=sspec.per_name_frac)
    return CrossSectionalAllocator(
        gross_target_frac=sspec.gross_target_frac,
        top_frac=sspec.top_frac,
        bottom_frac=sspec.bottom_frac,
    )
