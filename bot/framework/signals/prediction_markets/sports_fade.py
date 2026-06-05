# bot/framework/signals/prediction_markets/sports_fade.py
# ============================================================================
# STRATEGY CARD
#   name      : run_fade           desk: prediction_markets   status: RESEARCH
#   thesis    : during a game, a quick run (e.g. 10-0) makes the market
#               overreact on the other team's win prob; BIG, FAST drops are
#               mostly noise and revert. Fade big/rare overreactions only.
#   signal    : per-market state machine. Enter LONG (buy the dipped YES) on a
#               fast drop >= entry_drop (optionally with a min speed and away
#               from the p~0.5 fee peak). value() = conviction (drop/entry_drop).
#   entry/exit: ENTRY  : fast drop >= entry_drop, price in band, speed/peak ok
#               EXITS  : reverted (recovered reversion_frac of the drop) |
#                        stopped (fell another stop_drop — move was real) |
#                        timed_out (held max_hold bars) | settled (game ends)
#   risk      : PER-NAME stops live HERE (stop_drop + max_hold time-stop). Sizing
#               by EventFadeAllocator (fixed count, optional conviction scaling).
#               Book-level gross/net/drawdown still enforced by RiskMonitor.
#   costs     : edge is small; taker spread + Kalshi fees (worst near p=0.5) can
#               exceed it. Use bigger entry_drop, avoid_band, and maker entries.
#               See docs/strategies/sports-run-fade.md.
# ============================================================================
"""Fade the overreaction to an in-game run. Detects the overreaction from PRICE
alone (Kalshi gives no score), so it can't tell a reverting run from real news
(an injury) — the stop is the defense. Per-market O(1) state machine.
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

    def __init__(self, instrument, spec, *,
                 lookback: int = 4,            # window for the drop (small = fast)
                 entry_drop: float = 0.15,     # min drop to fade — BIGGER = rarer/better
                 min_drop_per_bar: float = 0.0,  # optional speed floor (drop/bar); 0=off
                 reversion_frac: float = 0.5,  # exit once this much of the drop reverts
                 stop_drop: float = 0.10,      # extra drop below entry -> stop out
                 max_hold: int = 15,           # bars before time-stop
                 min_price: float = 0.10,      # don't fade near the 0/1 extremes
                 max_price: float = 0.90,
                 avoid_lo: float = 0.0,        # skip entries with price in (avoid_lo,
                 avoid_hi: float = 0.0):       # avoid_hi) — dodge the p~0.5 fee peak
        super().__init__(instrument, spec)
        self.lookback = lookback
        self.entry_drop = entry_drop
        self.min_drop_per_bar = min_drop_per_bar
        self.reversion_frac = reversion_frac
        self.stop_drop = stop_drop
        self.max_hold = max_hold
        self.min_price = min_price
        self.max_price = max_price
        self.avoid_lo = avoid_lo
        self.avoid_hi = avoid_hi

        self._prices: deque[float] = deque(maxlen=lookback + 1)
        self.state = "FLAT"
        self.entry_price: float | None = None
        self.baseline: float | None = None
        self.conviction = 0.0
        self.bars_held = 0
        self._value = 0.0
        self.trades: list[dict] = []

    # --- entry test (kept separate so the rules are easy to read) ------------
    def _entry_ok(self, price: float, drop: float) -> bool:
        if drop < self.entry_drop:                          # big enough?
            return False
        if not (self.min_price <= price <= self.max_price):  # not at extremes
            return False
        if self.min_drop_per_bar and (drop / self.lookback) < self.min_drop_per_bar:
            return False                                     # fast enough?
        if self.avoid_lo < price < self.avoid_hi:            # away from fee peak?
            return False
        return True

    def update(self, state, event: Event) -> None:
        p = state.price()
        if p is None or not (0.0 < p < 1.0):
            return
        self._prices.append(p)

        if self.state == "FLAT":
            if len(self._prices) > self.lookback:
                past = self._prices[0]            # price `lookback` bars ago
                drop = past - p                    # positive => price fell
                if self._entry_ok(p, drop):
                    self.state = "LONG"
                    self.entry_price = p
                    self.baseline = past
                    self.conviction = drop / self.entry_drop   # >=1; bigger run -> bigger bet
                    self.bars_held = 0
                    self._value = self.conviction
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
            "conviction": round(self.conviction, 2),
            "bars_held": self.bars_held,
            "reason": reason,
            "move": round(price - self.entry_price, 4),  # +ve = profitable (decision prices)
        })
        self.state = "FLAT"
        self.entry_price = self.baseline = None
        self.conviction = 0.0
        self.bars_held = 0
        self._value = 0.0

    def value(self) -> float | None:
        # conviction while LONG (EventFadeAllocator can scale size by it), 0 when FLAT
        return self._value
