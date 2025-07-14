# bot/strategies/insider_simple.py
from typing import Optional, Dict
from bot.risk.size import dollar_position
from bot.brokers.alpaca import AlpacaBroker

TARGET_DOLLARS = 50
SIGNIFICANT_ROLES = ("CEO", "CFO", "Director")  # simplistic placeholder

def decide_trade(filing: Dict, broker: AlpacaBroker) -> Optional[Dict]:
    """
    Very first heuristic:
    - Trade only Form 4 insider buys (we'll refine size filters later)
    - Always buy 1 share just to prove the pipeline
    Return an order dict or None.
    """
    if filing["form"] != "4":
        return None

    # crude role filter using title text
    title_lower = filing["title"].lower()
    if not any(role.lower() in title_lower for role in SIGNIFICANT_ROLES):
        return None
    
    price = broker.current_price(filing["ticker"])
    qty = dollar_position(price)
    if qty == 0:
        return None
    
    return {"action": "BUY", "symbol": filing["ticker"], "qty": qty, "entry_price": price}
