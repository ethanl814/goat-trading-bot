# bot/risk/exit.py
from datetime import datetime, timedelta, timezone
from typing import Optional

STOP_PCT   = 0.10   # sell if –10 %
PROFIT_PCT = 0.15   # sell if +15 %
MAX_DAYS   = 30     # sell after 30 days

def should_exit(entry_price: float, current_price: float, entry_time: datetime) -> Optional[str]:
    if current_price <= entry_price * (1 - STOP_PCT):
        return "STOP"
    if current_price >= entry_price * (1 + PROFIT_PCT):
        return "TP"
    if datetime.now(timezone.utc) - entry_time >= timedelta(days=MAX_DAYS):
        return "TIME"
    return None
