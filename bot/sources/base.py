# bot/sources/base.py
from abc import ABC, abstractmethod
from threading import Event as StopEvent
from typing import Callable

from bot.core.events import Event


class SignalSource(ABC):
    """A producer of Events. Runs in its own thread, owned by the engine.

    `run` must loop until `stop` is set, calling `emit(event)` for each signal.
    It should be resilient: catch its own transient errors and keep going,
    rather than letting one bad poll kill the source.
    """
    name: str = "source"

    @abstractmethod
    def run(self, emit: Callable[[Event], None], stop: StopEvent) -> None:
        raise NotImplementedError
