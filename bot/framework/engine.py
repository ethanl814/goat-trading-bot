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

from bot.framework.allocator import Allocator
from bot.framework.broker import Order, SimBroker
from bot.framework.events import Clock, Event, MARKET_EVENTS, Resolution
from bot.framework.recorder import Recorder
from bot.framework.risk import RiskMonitor
from bot.framework.signals.base import Signal
from bot.framework.sources import Source
from bot.framework.state import MarketState
from bot.framework.universe import Universe

log = logging.getLogger(__name__)

_SENTINEL = object()  # pushed once all sources finish (backtest termination)


class EventEngine:
    def __init__(
        self,
        *,
        sources: list[Source],
        universe: Universe,
        signal_factory,                      # (symbol, spec) -> Signal
        allocator: Allocator,
        risk: RiskMonitor,
        broker: SimBroker,
        recorder: Recorder | None = None,
    ):
        self.sources = sources
        self.universe = universe
        self.allocator = allocator
        self.risk = risk
        self.broker = broker
        self.recorder = recorder

        self.states: dict[str, MarketState] = {}
        self.signals: dict[str, Signal] = {}
        for spec in universe.active():
            self.states[spec.symbol] = MarketState(spec)
            self.signals[spec.symbol] = signal_factory(spec.symbol, spec)

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
        log.info("engine started | %d instruments | %d sources",
                 len(self.signals), len(self.sources))
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
        sig = self.signals.get(event.instrument)
        if sig is not None:
            sig.update(st, event)

    def _on_resolution(self, event: Resolution) -> None:
        sym = event.instrument
        fill = self.broker.settle(sym, event.value)
        if fill and self.recorder:
            self.recorder.record_fill(fill)
        self.universe.remove(sym)
        self.states.pop(sym, None)
        self.signals.pop(sym, None)

    # --- the throttled decision step ----------------------------------------
    def _decide(self, clock: Clock) -> None:
        equity = self.broker.equity(self.states)
        self.risk.check_drawdown(equity)  # may trip the kill switch

        sigvals = {sym: sig.value() for sym, sig in self.signals.items()}
        specs = {s.symbol: s for s in self.universe.active()}
        targets = self.allocator.targets(sigvals, self.states, specs, equity)
        targets = self.risk.gate(targets, self.states, specs, equity)

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
