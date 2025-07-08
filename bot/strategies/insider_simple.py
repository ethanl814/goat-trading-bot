# bot/strategies/insider_simple.py
from typing import Optional, Dict

SIGNIFICANT_ROLES = ("CEO", "CFO", "Director")  # simplistic placeholder

def decide_trade(filing: Dict) -> Optional[Dict]:
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

    return {"action": "BUY", "symbol": filing["ticker"], "qty": 1}
