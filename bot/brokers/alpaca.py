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

    # --- market-data helpers (best-effort, defensive) ---
    def avg_daily_volume(self, symbol: str, days: int = 20):
        """Return average daily volume over `days`. Returns None on failure."""
        try:
            bars = self.api.get_barset(symbol, 'day', limit=days)[symbol]
            if not bars:
                return None
            vols = [b.v for b in bars if getattr(b, 'v', None) is not None]
            return sum(vols) / len(vols) if vols else None
        except Exception:
            return None

    def percent_since_week_low(self, symbol: str, days: int = 7):
        """Percent distance from the lowest close over the last `days` days. None on failure."""
        try:
            bars = self.api.get_barset(symbol, 'day', limit=days)[symbol]
            if not bars:
                return None
            lows = [b.l for b in bars if getattr(b, 'l', None) is not None]
            closes = [b.c for b in bars if getattr(b, 'c', None) is not None]
            if not lows or not closes:
                return None
            low = min(lows)
            latest = closes[-1]
            if low <= 0:
                return None
            return (latest - low) / low * 100
        except Exception:
            return None

    def bid_ask_spread(self, symbol: str):
        """Return current bid-ask spread (ask - bid) or None on failure."""
        try:
            q = self.api.get_latest_quote(symbol)
            return None if (q is None or q.bidprice is None or q.askprice is None) else (q.askprice - q.bidprice)
        except Exception:
            return None

    def intraday_volatility(self, symbol: str, minutes: int = 60):
        """Return a simple intraday volatility estimate (stddev of minute returns); None on failure."""
        try:
            bars = self.api.get_barset(symbol, '1Min', limit=minutes)[symbol]
            if not bars or len(bars) < 2:
                return None
            closes = [b.c for b in bars]
            returns = []
            for i in range(1, len(closes)):
                prev = closes[i - 1]
                if prev:
                    returns.append((closes[i] - prev) / prev)
            if not returns:
                return None
            # sample standard deviation
            import math
            mean = sum(returns) / len(returns)
            var = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1) if len(returns) > 1 else 0.0
            return math.sqrt(var)
        except Exception:
            return None
