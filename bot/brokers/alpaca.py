# bot/brokers/alpaca.py
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import logging
import os
from dotenv import load_dotenv
import alpaca_trade_api as tradeapi

load_dotenv()  # read .env

log = logging.getLogger(__name__)

# IEX (free) data is delayed ~15 min; pad the window end so requests don't ask
# for data we're not entitled to in real time.
_DATA_DELAY = timedelta(minutes=16)


@dataclass
class AlpacaBroker:
    paper: bool = True
    feed: str = field(default_factory=lambda: os.getenv("ALPACA_DATA_FEED", "iex"))
    # Explicit creds override the environment — lets the mode/credential layer
    # (bot/framework/modes.py) point this at the paper vs live account. When None,
    # falls back to the legacy ALPACA_KEY_ID/SECRET/BASE_URL env vars.
    key_id: str | None = None
    secret_key: str | None = None
    base_url: str | None = None

    def __post_init__(self):
        key = self.key_id or os.getenv("ALPACA_KEY_ID")
        secret = self.secret_key or os.getenv("ALPACA_SECRET_KEY")
        base_url = self.base_url or os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
        self.api = tradeapi.REST(key, secret, base_url, api_version="v2")

    # --- account / order interface ------------------------------------------
    def account_info(self):
        return self.api.get_account()

    def submit_buy_market(self, symbol: str, qty: int):
        return self.api.submit_order(symbol=symbol, qty=qty, side="buy",
                                     type="market", time_in_force="day")

    def submit_sell_market(self, symbol: str, qty: int):
        return self.api.submit_order(symbol=symbol, qty=qty, side="sell",
                                     type="market", time_in_force="day")

    def current_price(self, symbol: str) -> float | None:
        try:
            return self.api.get_latest_trade(symbol).price
        except Exception as e:
            log.warning("current_price(%s) failed: %s", symbol, e)
            return None

    # --- market-data helpers --------------------------------------------------
    def _bars(self, symbol: str, timeframe, lookback_days: int, tail: int | None = None):
        """Fetch historical bars over a date window and return the most recent
        `tail` of them (or all). Returns [] on any failure (logged)."""
        try:
            end = datetime.now(timezone.utc) - _DATA_DELAY
            start = end - timedelta(days=lookback_days)
            bars = list(self.api.get_bars(symbol, timeframe,
                                          start=start.isoformat(),
                                          end=end.isoformat(),
                                          feed=self.feed))
            return bars[-tail:] if tail else bars
        except Exception as e:
            log.warning("get_bars(%s, %s) failed: %s", symbol, timeframe, e)
            return []

    def daily_closes(self, symbol: str, limit: int = 252) -> list[float]:
        """Most recent `limit` daily closes (oldest -> newest)."""
        # ~1.5 calendar days per trading day covers weekends/holidays.
        bars = self._bars(symbol, tradeapi.TimeFrame.Day,
                          lookback_days=int(limit * 1.6) + 10, tail=limit)
        return [b.c for b in bars if getattr(b, "c", None) is not None]

    def avg_daily_volume(self, symbol: str, days: int = 20) -> float | None:
        bars = self._bars(symbol, tradeapi.TimeFrame.Day,
                          lookback_days=int(days * 1.6) + 10, tail=days)
        vols = [b.v for b in bars if getattr(b, "v", None) is not None]
        return sum(vols) / len(vols) if vols else None

    def percent_since_week_low(self, symbol: str, days: int = 7) -> float | None:
        bars = self._bars(symbol, tradeapi.TimeFrame.Day,
                          lookback_days=int(days * 1.6) + 10, tail=days)
        lows = [b.l for b in bars if getattr(b, "l", None) is not None]
        closes = [b.c for b in bars if getattr(b, "c", None) is not None]
        if not lows or not closes:
            return None
        low = min(lows)
        if low <= 0:
            return None
        return (closes[-1] - low) / low * 100

    def bid_ask_spread(self, symbol: str) -> float | None:
        try:
            q = self.api.get_latest_quote(symbol, feed=self.feed)
            if q.bid_price is None or q.ask_price is None:
                return None
            return q.ask_price - q.bid_price
        except Exception as e:
            log.warning("bid_ask_spread(%s) failed: %s", symbol, e)
            return None

    def intraday_volatility(self, symbol: str, minutes: int = 60) -> float | None:
        # Look back a few days so we still get a session's worth of bars when the
        # market is closed, then take the most recent `minutes` bars.
        bars = self._bars(symbol, tradeapi.TimeFrame.Minute, lookback_days=5, tail=minutes)
        closes = [b.c for b in bars if getattr(b, "c", None) is not None]
        if len(closes) < 2:
            return None
        returns = [(closes[i] - closes[i - 1]) / closes[i - 1]
                   for i in range(1, len(closes)) if closes[i - 1]]
        if len(returns) < 2:
            return None
        mean = sum(returns) / len(returns)
        var = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
        return var ** 0.5
