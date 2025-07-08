# bot/brokers/alpaca.py
from dataclasses import dataclass
import os
from dotenv import load_dotenv
import alpaca_trade_api as tradeapi

load_dotenv()  # read .env

@dataclass
class AlpacaBroker:
    paper: bool = True

    def __post_init__(self):
        key = os.getenv("ALPACA_KEY_ID")
        secret = os.getenv("ALPACA_SECRET_KEY")
        base_url = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
        self.api = tradeapi.REST(key, secret, base_url, api_version="v2")

    # --- public interface ---
    def account_info(self):
        return self.api.get_account()

    def submit_buy_market(self, symbol: str, qty: int):
        return self.api.submit_order(symbol=symbol,
                                     qty=qty,
                                     side="buy",
                                     type="market",
                                     time_in_force="day")

    def submit_sell_market(self, symbol: str, qty: int):
        return self.api.submit_order(symbol=symbol,
                                     qty=qty,
                                     side="sell",
                                     type="market",
                                     time_in_force="day")


    def current_price(self, symbol: str):
        bar = self.api.get_latest_trade(symbol)
        return bar.price
