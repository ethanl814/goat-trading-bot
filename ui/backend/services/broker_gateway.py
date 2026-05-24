# Unified broker gateway so the UI can route orders to whichever venue a strategy needs
# (Alpaca for equities, Kalshi/Polymarket for prediction markets, a CEX/DEX for crypto, etc.).
from typing import Protocol


class Broker(Protocol):
    def account_info(self): ...
    def submit_buy_market(self, symbol: str, qty: float): ...
    def submit_sell_market(self, symbol: str, qty: float): ...
    def current_price(self, symbol: str) -> float: ...


def get_broker(venue: str) -> Broker:
    raise NotImplementedError
