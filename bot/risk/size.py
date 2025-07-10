# bot/risk/size.py
def dollar_position(qty_dollars: float, price: float) -> int:
    """
    Return integer share count so trade ≈ qty_dollars but ≥1 share.
    Skip trade if price is zero or > qty_dollars (can't buy at least 1).
    """
    if price <= 0 or price > qty_dollars:
        return 0
    return max(1, int(qty_dollars // price))
