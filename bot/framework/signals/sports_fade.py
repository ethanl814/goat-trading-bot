# bot/framework/signals/sports_fade.py
"""Run-reversal fade — fade the overreaction to an in-game run.

THESIS (yours): during a game, when a team makes a quick run (e.g. 10-0 in Q1),
the market overreacts — the *other* team's win probability drops too far, too
fast. That drop is mostly noise (runs are part of the game) and tends to revert.
So: when a market's price falls sharply and quickly, BUY it (fade the drop), then
exit when it reverts part-way back — with a stop if the move was real (injury,
ejection, actual lead) and a time-stop so we don't ride it to resolution.

Per-market state machine (one instance per contract, O(1) per tick):

    FLAT ──[fast drop >= entry_drop, price in band]──▶ LONG
    LONG ──[price recovers reversion_frac of the drop]──▶ FLAT   (take profit)
    LONG ──[price falls another stop_drop below entry]──▶ FLAT   (stop: move was real)
    LONG ──[held >= max_hold bars]──────────────────────▶ FLAT   (time stop)

`value()` returns 1.0 while LONG (so an `EventFadeAllocator` holds a fixed long)
and 0.0 when FLAT (allocator exits). The signal owns the *decision*; sizing,
fills, fees and settlement are the allocator's / broker's job.

It detects the overreaction from the PRICE move alone — Kalshi doesn't expose the
score. That means it can't tell a reverting run from real news (an injury); the
stop is the defense against that. A future version can gate entries on a live
game-state feed (only fade run-driven moves). All thresholds are in probability
units (e.g. 0.08 = 8 cents) and tunable via `signal_params` in control.py.
"""
from __future__ import annotations

from collections import deque

from bot.framework.events import Event
from bot.framework.instruments import AssetClass
from bot.framework.registry import register
from bot.framework.signals.base import Signal


@register("run_fade")
class RunReversalFade(Signal):
    name = "run_fade"
    applies_to = (AssetClass.PREDICTION_MARKET,)

    def __init__(self, instrument, spec, *, lookback: int = 5, entry_drop: float = 0.08,
                 reversion_frac: float = 0.5, stop_drop: float = 0.10, max_hold: int = 15,
                 min_price: float = 0.10, max_price: float = 0.90):
        super().__init__(instrument, spec)
        self.lookback = lookback            # bars over which to measure the "fast" drop
        self.entry_drop = entry_drop        # min drop (prob units) to call it an overreaction
        self.reversion_frac = reversion_frac  # exit once this fraction of the drop reverts
        self.stop_drop = stop_drop          # extra drop below entry that stops us out
        self.max_hold = max_hold            # max bars to hold before time-stop
        self.min_price = min_price          # don't fade near the 0/1 extremes
        self.max_price = max_price

        self._prices: deque[float] = deque(maxlen=lookback + 1)
        self.state = "FLAT"
        self.entry_price: float | None = None
        self.baseline: float | None = None   # pre-run price we expect to revert toward
        self.bars_held = 0
        self._value = 0.0
        self.trades: list[dict] = []          # per-trade log for the backtest report

    def update(self, state, event: Event) -> None:
        p = state.price()
        if p is None or not (0.0 < p < 1.0):
            return
        self._prices.append(p)

        if self.state == "FLAT":
            if len(self._prices) > self.lookback:
                past = self._prices[0]              # price `lookback` bars ago
                drop = past - p                      # positive => price fell
                if drop >= self.entry_drop and self.min_price <= p <= self.max_price:
                    self.state = "LONG"
                    self.entry_price = p
                    self.baseline = past
                    self.bars_held = 0
                    self._value = 1.0
        else:  # LONG — manage the open fade
            self.bars_held += 1
            target = self.entry_price + self.reversion_frac * (self.baseline - self.entry_price)
            if p >= target:
                self._close(p, "reverted")
            elif p <= self.entry_price - self.stop_drop:
                self._close(p, "stopped")
            elif self.bars_held >= self.max_hold:
                self._close(p, "timed_out")

    def _close(self, price: float, reason: str) -> None:
        self.trades.append({
            "instrument": self.instrument,
            "entry": round(self.entry_price, 4),
            "exit": round(price, 4),
            "baseline": round(self.baseline, 4),
            "bars_held": self.bars_held,
            "reason": reason,
            "move": round(price - self.entry_price, 4),  # +ve = profitable fade (decision prices)
        })
        self.state = "FLAT"
        self.entry_price = self.baseline = None
        self.bars_held = 0
        self._value = 0.0

    def value(self) -> float | None:
        return self._value
