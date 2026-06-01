# bot/sources/clock.py
import logging
from threading import Event as StopEvent
from typing import Callable

from bot.core.events import Event, EventType
from bot.sources.base import SignalSource

log = logging.getLogger(__name__)


class ClockSource(SignalSource):
    """Emits a TICK event every `interval` seconds. The engine uses TICKs to
    drive periodic work — currently exit checks on open positions."""
    name = "clock"

    def __init__(self, interval: float = 180):
        self.interval = interval

    def run(self, emit: Callable[[Event], None], stop: StopEvent) -> None:
        # Fire one immediately so exits are evaluated at startup.
        while not stop.is_set():
            emit(Event(type=EventType.TICK, symbol=None, source=self.name))
            stop.wait(self.interval)
