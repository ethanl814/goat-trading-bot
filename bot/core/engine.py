# bot/core/engine.py
"""The event-driven engine.

Design (classic producer/consumer):

    sources (threads)             engine (1 consumer thread)
    ┌───────────────┐  Event      ┌──────────────────────────┐
    │ EdgarSource   │──┐          │ queue.get()              │
    │ ClockSource   │──┼─────────▶│   → dispatch to strategies│
    │ AlpacaStream  │──┘          │   → execute Orders        │
    └───────────────┘             │   → run exits on TICK     │
                                  └──────────────────────────┘

Each source runs in its own thread and pushes normalized `Event`s onto a
thread-safe queue. The engine consumes them one at a time and routes each to
every enabled strategy subscribed to that event type. Strategies return
`Order`s; the engine is the only thing that talks to the broker, tracks
positions, and evaluates exits. This is the seam where low-latency streaming
sources slot in next to slow polling ones without changing any strategy.
"""
import logging
import threading
from datetime import datetime, timezone
from queue import Empty, Queue

from bot.brokers.alpaca import AlpacaBroker
from bot.core.events import Event, EventType, Order
from bot.core.strategy import Strategy
from bot.risk.exit import should_exit
from bot.sources.base import SignalSource
from bot.utils.logger import log_close, log_trade
from bot.utils.positions import add_position, load_open, remove_position

log = logging.getLogger(__name__)


class Engine:
    def __init__(self, broker: AlpacaBroker, strategies: list[Strategy]):
        self.broker = broker
        self.strategies = strategies
        self.queue: "Queue[Event]" = Queue()
        self.sources: list[SignalSource] = []
        self._stop = threading.Event()

    def add_source(self, source: SignalSource) -> None:
        self.sources.append(source)

    # --- lifecycle -----------------------------------------------------------
    def run(self) -> None:
        for src in self.sources:
            threading.Thread(target=self._run_source, args=(src,),
                             name=f"src-{src.name}", daemon=True).start()
        log.info("Engine started | strategies=%s | sources=%s",
                 [s.name for s in self.strategies], [s.name for s in self.sources])
        try:
            while not self._stop.is_set():
                try:
                    event = self.queue.get(timeout=1.0)
                except Empty:
                    continue
                self._dispatch(event)
        except KeyboardInterrupt:
            log.info("Manual stop — shutting down")
        finally:
            self._stop.set()

    def _run_source(self, src: SignalSource) -> None:
        try:
            src.run(self.queue.put, self._stop)
        except Exception:
            log.exception("source %s crashed", src.name)

    # --- routing -------------------------------------------------------------
    def _dispatch(self, event: Event) -> None:
        if event.type == EventType.TICK:
            self._check_exits()
            return
        for strat in self.strategies:
            if not strat.enabled or event.type not in strat.subscribes:
                continue
            try:
                order = strat.on_event(event, self.broker)
            except Exception:
                log.exception("strategy %s errored on %s", strat.name, event.type)
                continue
            if order:
                self._execute(order, event)

    # --- execution -----------------------------------------------------------
    def _execute(self, order: Order, event: Event) -> None:
        open_symbols = {p["symbol"] for p in load_open()}
        if order.side == "buy" and order.symbol in open_symbols:
            log.info("skip BUY %s (%s): position already open", order.symbol, order.strategy)
            return
        try:
            if order.side == "buy":
                resp = self.broker.submit_buy_market(order.symbol, order.qty)
                record = event.payload if event.type == EventType.FILING else {
                    "ticker": order.symbol, "form": "-"}
                log_trade(record, resp)
                add_position({
                    "symbol": order.symbol,
                    "qty": order.qty,
                    "entry_price": order.entry_price,
                    "entry_time": datetime.now(timezone.utc),
                    "strategy": order.strategy,
                })
                log.info("BUY %s x%s @ %s [%s]", order.symbol, order.qty,
                         order.entry_price, order.strategy)
            else:
                self.broker.submit_sell_market(order.symbol, order.qty)
                log.info("SELL %s x%s [%s]", order.symbol, order.qty, order.strategy)
        except Exception:
            log.exception("order failed: %s", order)

    def _check_exits(self) -> None:
        for pos in load_open():
            price = self.broker.current_price(pos["symbol"])
            if price is None:
                continue
            reason = should_exit(pos["entry_price"], price, pos["entry_time"])
            if not reason:
                continue
            try:
                self.broker.submit_sell_market(pos["symbol"], pos["qty"])
                log_close(pos, price, reason)
                remove_position(pos["symbol"])
                log.info("EXIT %s via %s @ %s", pos["symbol"], reason, price)
            except Exception:
                log.exception("exit failed for %s", pos["symbol"])
