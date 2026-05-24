# Payoff calculator for combined derivative positions.
# A "leg" describes one instrument (stock, call, put, future, binary, etc.)
# and the combiner maps underlying price -> aggregate P&L.
from dataclasses import dataclass
from typing import Literal


@dataclass
class Leg:
    kind: Literal["stock", "call", "put", "future", "binary"]
    strike: float | None
    qty: float
    premium: float
    expiry: str | None


def payoff_at(legs: list[Leg], underlying_price: float) -> float:
    raise NotImplementedError


def payoff_curve(legs: list[Leg], price_range: tuple[float, float], steps: int = 200) -> list[tuple[float, float]]:
    raise NotImplementedError
