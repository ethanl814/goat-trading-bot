# bot/framework/instruments.py
"""The asset-class abstraction: `InstrumentSpec` (what an instrument *is*) and
`AssetClass`/`PriceKind` enums.

This is the heart of the multi-asset generalization. The core never branches on
asset class — instead each instrument carries a spec declaring its constraints
(tick/lot size, fees, shortability, caps, lifecycle, settlement bounds), and the
allocator / SimBroker / risk monitor consume those declarations *generically*.
Adding FX or options later = emit specs with the right fields, write one adapter,
touch nothing here.

`MarketAdapter` (in adapters/) supplies the *dynamic* behavior (live feed,
calendar, roll); `InstrumentSpec` is the *static* description it pairs with.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class AssetClass(str, Enum):
    EQUITY = "equity"
    CRYPTO = "crypto"
    FUTURE = "future"
    PREDICTION_MARKET = "prediction_market"


class PriceKind(str, Enum):
    CONTINUOUS = "continuous"    # equities / crypto / futures: an open-ended price
    PROBABILITY = "probability"  # prediction markets: a price in [0,1] that resolves


@dataclass(frozen=True)
class InstrumentSpec:
    symbol: str
    asset_class: AssetClass
    price_kind: PriceKind = PriceKind.CONTINUOUS

    # --- fill mechanics (consumed generically by SimBroker) ------------------
    tick_size: float = 0.01          # price increment
    lot_size: float = 1.0            # qty increment (1 = whole shares/contracts)
    contract_multiplier: float = 1.0  # $ per 1.0 price per 1 unit (futures > 1)
    taker_fee_bps: float = 0.0
    maker_fee_bps: float = 0.0
    slippage_bps: float = 1.0        # sim slippage as a fraction of price (bps)
    slippage_price: float = 0.0      # sim slippage as an ABSOLUTE price offset (e.g.
                                     # half-spread in cents); preferred when > 0
    # Fee model: "bps" (notional * taker_fee_bps) or "kalshi"
    # (ceil(fee_coefficient * contracts * p * (1-p)), rounded up to the cent).
    fee_kind: str = "bps"
    fee_coefficient: float = 0.07

    # --- position constraints (consumed generically by allocator + risk) -----
    shortable: bool = True
    long_only: bool = False
    max_position_qty: float | None = None  # per-name/per-contract cap

    # --- lifecycle ------------------------------------------------------------
    expires: bool = False
    expiry: datetime | None = None
    settle_low: float = 0.0          # settlement bounds (probability resolves in [0,1])
    settle_high: float = 1.0

    # --- helpers --------------------------------------------------------------
    def round_price(self, price: float) -> float:
        if self.tick_size <= 0:
            return price
        return round(price / self.tick_size) * self.tick_size

    def round_qty(self, qty: float) -> float:
        if self.lot_size <= 0:
            return qty
        # truncate toward zero so we never round a target *up* past a cap
        lots = int(qty / self.lot_size)
        return lots * self.lot_size

    def fee(self, qty: float, price: float, taker: bool = True) -> float:
        if self.fee_kind == "kalshi":
            # Kalshi trading fee: round_up(coef * contracts * price * (1 - price)),
            # rounded up to the next cent. Highest near p=0.5, ~0 near 0/1.
            import math
            raw = self.fee_coefficient * abs(qty) * price * (1.0 - price)
            # round up to the next cent; the epsilon guards against fp dust
            # (e.g. 1.75*100 == 175.0000000000003) spuriously bumping a cent.
            return math.ceil(raw * 100.0 - 1e-9) / 100.0
        bps = self.taker_fee_bps if taker else self.maker_fee_bps
        notional = abs(qty) * price * self.contract_multiplier
        return notional * bps / 1e4

    def apply_slippage(self, ref_price: float, buying: bool) -> float:
        """Fill price after slippage moves against us. Absolute (`slippage_price`,
        e.g. half-spread) takes precedence over bps; result is tick-rounded and
        clamped to settlement bounds for probability instruments."""
        if self.slippage_price > 0:
            fill = ref_price + self.slippage_price if buying else ref_price - self.slippage_price
        else:
            slip = self.slippage_bps / 1e4
            fill = ref_price * (1 + slip) if buying else ref_price * (1 - slip)
        fill = self.round_price(fill)
        if self.price_kind is PriceKind.PROBABILITY:
            fill = max(self.settle_low, min(self.settle_high, fill))
        return fill

    @property
    def can_short(self) -> bool:
        return self.shortable and not self.long_only
