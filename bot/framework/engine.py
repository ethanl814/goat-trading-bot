# bot/framework/engine.py
"""The async EventEngine — the central loop, identical across both modes.

    sources (async tasks)            engine (1 consumer)
    ┌──────────────────┐  Event      ┌─────────────────────────────────────┐
    │ MarketAdapter(s)  │──┐         │ await queue.get()                    │
    │ ClockSource       │──┼────────▶│  market event → update state+signal  │
    │ (or ReplaySource) │──┘         │  Resolution   → settle + drop name   │
    └──────────────────┘             │  Clock        → throttled decision   │
                                     └─────────────────────────────────────┘

Data flow on a Clock (the conflated decision step): snapshot current signal
values → allocator builds targets → risk monitor gates (and may trip the kill
switch) → diff against positions → SimBroker fills → recorder logs fills + the
equity point. Every market event keeps state current in O(1); the expensive
allocation only runs on the throttled Clock cadence, coalescing bursts.
"""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict

from bot.framework.broker import Broker, Order
from bot.framework.events import Clock, Event, MARKET_EVENTS, Resolution
from bot.framework.recorder import Recorder
from bot.framework.risk import RiskMonitor
from bot.framework.sources import Source
from bot.framework.state import MarketState
from bot.framework.strategy import StrategyRunner
from bot.framework.universe import Universe

log = logging.getLogger(__name__)

_SENTINEL = object()  # pushed once all sources finish (backtest termination)


class EventEngine:
    def __init__(
        self,
        *,
        sources: list[Source],
        universe: Universe,
        strategies: list[StrategyRunner],
        risk: RiskMonitor,
        broker: Broker,
        recorder: Recorder | None = None,
    ):
        self.sources = sources
        self.universe = universe
        self.strategies = [s for s in strategies if s.enabled]
        self.risk = risk
        self.broker = broker
        self.recorder = recorder

        # One shared MarketState per instrument (union of all strategy universes).
        self.states: dict[str, MarketState] = {
            spec.symbol: MarketState(spec) for spec in universe.active()
        }

    # --- lifecycle -----------------------------------------------------------
    async def run(self, stop: asyncio.Event | None = None) -> None:
        stop = stop or asyncio.Event()
        queue: asyncio.Queue = asyncio.Queue()

        async def emit(event: Event) -> None:
            await queue.put(event)

        async def supervise() -> None:
            # when every source is exhausted (backtest) push the sentinel so the
            # consumer stops; in live mode sources run until `stop` is set.
            await asyncio.gather(*(s.run(emit, stop) for s in self.sources),
                                 return_exceptions=True)
            await queue.put(_SENTINEL)

        sup = asyncio.create_task(supervise())
        log.info("engine started | %d instruments | %d strategies | %d sources",
                 len(self.states), len(self.strategies), len(self.sources))
        try:
            while not stop.is_set():
                event = await queue.get()
                if event is _SENTINEL:
                    break
                self._dispatch(event)
        finally:
            stop.set()
            sup.cancel()
            if self.recorder:
                self.recorder.close()
            log.info("engine stopped | realized PnL=%.2f | equity=%.2f",
                     self.broker.realized, self.broker.equity(self.states))

    # --- dispatch ------------------------------------------------------------
    def _dispatch(self, event: Event) -> None:
        if isinstance(event, Clock):
            self._decide(event)
        elif isinstance(event, Resolution):
            self._on_resolution(event)
        elif isinstance(event, MARKET_EVENTS):
            self._on_market_event(event)

    def _on_market_event(self, event: Event) -> None:
        st = self.states.get(event.instrument)
        if st is None:
            return  # not in universe (or already resolved away)
        st.update(event)
        # fan the event out to every strategy that trades this instrument
        for strat in self.strategies:
            sig = strat.signals.get(event.instrument)
            if sig is not None:
                sig.update(st, event)

    def _on_resolution(self, event: Resolution) -> None:
        sym = event.instrument
        fill = self.broker.settle(sym, event.value)
        if fill and self.recorder:
            self.recorder.record_fill(fill)
        self.universe.remove(sym)
        self.states.pop(sym, None)
        for strat in self.strategies:
            strat.signals.pop(sym, None)

    # --- the throttled decision step ----------------------------------------
    def _decide(self, clock: Clock) -> None:
        equity = self.broker.equity(self.states)
        self.risk.check_drawdown(equity)  # may trip the kill switch

        specs = {s.symbol: s for s in self.universe.active()}

        # each strategy proposes targets over its own universe/capital slice;
        # sum them into one combined book, then gate the total once.
        book: dict[str, float] = defaultdict(float)
        for strat in self.strategies:
            sigvals = {sym: sig.value() for sym, sig in strat.signals.items()}
            sub_specs = {sym: specs[sym] for sym in strat.signals if sym in specs}
            sub_states = {sym: self.states[sym] for sym in strat.signals if sym in self.states}
            proposed = strat.allocator.targets(
                sigvals, sub_states, sub_specs, equity * strat.capital_frac)
            for sym, qty in proposed.items():
                book[sym] += qty

        targets = self.risk.gate(dict(book), self.states, specs, equity)

        # diff targets against current book -> orders for the delta
        names = set(targets) | set(self.broker.positions())
        for sym in names:
            spec = specs.get(sym) or self.broker.specs.get(sym)
            if spec is None:
                continue
            current = self.broker.position_qty(sym)
            delta = spec.round_qty(targets.get(sym, 0.0) - current)
            if delta == 0:
                continue
            st = self.states.get(sym)
            if st is None:
                continue
            fill = self.broker.submit(Order(sym, delta), st)
            if fill and self.recorder:
                self.recorder.record_fill(fill)

        self._record_equity(clock, specs)

    def _record_equity(self, clock: Clock, specs) -> None:
        if not self.recorder:
            return
        positions = self.broker.positions()
        gross = net = 0.0
        for sym, pos in positions.items():
            st = self.states.get(sym)
            price = st.price() if st else None
            if price is None:
                continue
            val = pos.qty * price * specs[sym].contract_multiplier
            gross += abs(val)
            net += val
        self.recorder.record_equity(
            clock.ts, self.broker.equity(self.states), self.broker.cash,
            gross, net, self.broker.realized, self.broker.unrealized(self.states))
