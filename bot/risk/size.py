# bot/risk/size.py
TARGET_DOLLARS = 100  # <— adjust per trade

def dollar_position(price: float) -> int:
    """Return share qty so trade ≈ TARGET_DOLLARS; 0 means skip."""
    if price <= 0 or price > TARGET_DOLLARS:
        return 0
    return max(1, int(TARGET_DOLLARS // price))
