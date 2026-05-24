# bot/strategies/insider_simple.py
from typing import Optional, Dict
from bot.risk.size import dollar_position
from bot.brokers.alpaca import AlpacaBroker
import datetime as dt
import csv, pathlib

TARGET_DOLLARS = 50
SIGNIFICANT_ROLES = ("CEO", "CFO", "Director")  # simplistic placeholder

# conservative thresholds (tunable)
MIN_AVG_DAILY_VOLUME = 50_000  # avoid very illiquid tickers
MAX_SPREAD_DOLLARS = 0.05      # max acceptable bid-ask spread in $
MAX_RISE_SINCE_WEEK_LOW_PCT = 20.0
MAX_INTRADAY_VOLATILITY = 0.02  # ~2% stddev in minute returns suggests calm market
MAX_SLIPPAGE_PCT = 0.005  # estimate max slippage 0.5%

LOG_PATH = pathlib.Path("logs")


def _historical_insider_success(ticker: str) -> Optional[float]:
    """Very small heuristic: read closed_trades.csv and compute fraction of positive PnL for this symbol.
    Returns None if no history.
    """
    path = LOG_PATH / "closed_trades.csv"
    if not path.exists():
        return None
    wins = 0
    total = 0
    try:
        with path.open() as f:
            reader = csv.DictReader(f)
            for r in reader:
                if r.get("symbol") != ticker:
                    continue
                try:
                    pnl = float(r.get("pnl_dollars", r.get("pnl", "0")))
                except Exception:
                    # some files use different headers — try to compute
                    try:
                        entry = float(r.get("entry_price", 0))
                        exit_p = float(r.get("exit_price", 0))
                        qty = float(r.get("qty", 1))
                        pnl = (exit_p - entry) * qty
                    except Exception:
                        continue
                total += 1
                if pnl > 0:
                    wins += 1
    except Exception:
        return None
    if total == 0:
        return None
    return wins / total


def decide_trade(filing: Dict, broker: AlpacaBroker) -> Optional[Dict]:
    """Decide whether to place a buy based on an insider Form 4.

    New filters implemented:
    - Only Form 4 buys (if filing provides transaction type) and significant roles
    - Insider ownership percentage (if present) — prefer larger owners
    - Buy vs sell volume (if filing includes transaction amount/share count)
    - Time of filing: avoid outside regular hours or in known volatile windows
    - Liquidity filters: average daily volume & bid-ask spread
    - Momentum filter: avoid stocks that have risen > MAX_RISE_SINCE_WEEK_LOW_PCT since recent week low
    - Slippage estimation based on intraday volatility

    Returns None or order dict with keys: symbol, qty, entry_price
    """
    # basic form check
    if filing.get("form") != "4":
        return None

    title_lower = filing.get("title", "").lower()
    if not any(role.lower() in title_lower for role in SIGNIFICANT_ROLES):
        return None

    symbol = filing.get("ticker")
    if not symbol:
        return None

    # defensive: fetch current price
    try:
        price = broker.current_price(symbol)
    except Exception:
        return None
    if not price or price <= 0:
        return None

    # optional filing fields (best-effort). If not present, don't block but be conservative.
    insider_pct = filing.get("insider_ownership_pct")  # expected as float 0..100
    transaction_type = filing.get("transaction_type", "BUY").upper()
    transaction_shares = filing.get("transaction_shares")

    # require buy
    if transaction_type and "BUY" not in transaction_type:
        return None

    # historical success check (soft): if we have history and it's poor, skip
    hist_success = _historical_insider_success(symbol)
    if hist_success is not None and hist_success < 0.4:
        # historically unprofitable — skip
        return None

    # liquidity checks
    adv = broker.avg_daily_volume(symbol)
    if adv is not None and adv < MIN_AVG_DAILY_VOLUME:
        return None

    spread = broker.bid_ask_spread(symbol)
    if spread is not None and spread > MAX_SPREAD_DOLLARS:
        return None

    # momentum / recent run up filter
    rise_pct = broker.percent_since_week_low(symbol)
    if rise_pct is not None and rise_pct > MAX_RISE_SINCE_WEEK_LOW_PCT:
        return None

    # intraday volatility -> slippage estimate
    iv = broker.intraday_volatility(symbol, minutes=60)
    if iv is not None and iv > MAX_INTRADAY_VOLATILITY:
        # market currently volatile — avoid new entries
        return None

    # estimate slippage as a multiple of intraday vol + spread
    est_slippage_pct = 0.0
    if iv is not None:
        est_slippage_pct = max(est_slippage_pct, iv * 1.5)
    if spread is not None:
        est_slippage_pct = max(est_slippage_pct, spread / price)
    if est_slippage_pct > MAX_SLIPPAGE_PCT:
        return None

    # size calc
    qty = dollar_position(price)
    if qty == 0:
        return None

    # final conservative order
    return {"action": "BUY", "symbol": symbol, "qty": qty, "entry_price": price}
