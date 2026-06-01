# bot/sources/edgar.py
import hashlib
import logging
from threading import Event as StopEvent
from typing import Callable

from bot.core.events import Event, EventType
from bot.data.edgar_feed import latest_filings
from bot.sources.base import SignalSource
from bot.utils.state import load_seen, save_seen

log = logging.getLogger(__name__)


class EdgarSource(SignalSource):
    """Polls the SEC EDGAR feed and emits a FILING event per *new* filing.

    Dedup lives here (not in the engine): the source owns the 'seen' set, so the
    engine never sees a filing twice. This is a polling source — latency is
    bounded by `interval`. Real-time market reactions come from streaming
    sources (see alpaca_stream.py)."""
    name = "edgar"

    def __init__(self, interval: float = 180):
        self.interval = interval
        self.seen = load_seen()

    def run(self, emit: Callable[[Event], None], stop: StopEvent) -> None:
        log.info("edgar source polling every %ss (%d already seen)",
                 self.interval, len(self.seen))
        while not stop.is_set():
            try:
                for filing in latest_filings():
                    fid = hashlib.sha1(filing["link"].encode()).hexdigest()
                    if fid in self.seen:
                        continue
                    self.seen.add(fid)
                    save_seen(self.seen)
                    emit(Event(type=EventType.FILING, symbol=filing["ticker"],
                               payload=filing, source=self.name))
            except Exception as e:
                log.warning("edgar poll failed: %s", e)
            stop.wait(self.interval)
