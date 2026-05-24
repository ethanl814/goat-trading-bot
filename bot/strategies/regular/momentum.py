# bot/strategies/momentum.py
"""
Momentum strategy using technical indicators and multi-timeframe confirmation.
This file intentionally keeps heavy computations local and uses the AlpacaBroker
market-data helpers where possible. The strategy is conservative and returns
None when indicators are not available or do not confirm an entry.

Key checks:
- stock price above a given moving average (50-day default)
- RSI between configured bounds (not overbought)
- MACD shows bullish crossover or positive histogram
- Moving average cross confirmation (e.g., 20d > 50d)
- Multi-timeframe uptrend confirmation (1D, 1W, 1M)
- Sector strength placeholder (requires external sector data)
- Optional simple Fama-French overlay: regress recent returns vs provided factors

The strategy exposes decide_trade(filing, broker) to match existing pattern.
"""
from typing import Optional, Dict
from bot.risk.size import dollar_position
from bot.brokers.alpaca import AlpacaBroker
import statistics, math

# thresholds
MIN_AVG_DAILY_VOLUME = 50_000
MIN_RSI = 40
MAX_RSI = 70
MA_SHORT = 20
MA_LONG = 50
MA_CONFIRM_SHORT = 50  # e.g., 50-day for base filter
MULTI_TF_REQUIRED = 2  # number of timeframes that must be uptrend


def _sma(values):
    return sum(values) / len(values) if values else None


def _rsi(closes, period=14):
    if len(closes) < period + 1:
        return None
    gains = []
    losses = []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        if diff > 0:
            gains.append(diff)
        else:
            losses.append(abs(diff))
    avg_gain = sum(gains[-period:]) / period if len(gains) >= period else (sum(gains) / period if gains else 0)
    avg_loss = sum(losses[-period:]) / period if len(losses) >= period else (sum(losses) / period if losses else 0)
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1 + rs))


def _macd(closes, fast=12, slow=26, signal=9):
    # simple EMA-based MACD; returns (macd_line, signal_line, histogram)
    def ema(values, span):
        if not values or span <= 0:
            return None
        k = 2 / (span + 1)
        ema_v = values[0]
        for v in values[1:]:
            ema_v = v * k + ema_v * (1 - k)
        return ema_v

    if len(closes) < slow + signal:
        return (None, None, None)
    macd_line = ema(closes[-(slow + 5):], fast) - ema(closes[-(slow + 5):], slow)
    # build signal using recent macd values
    # primitive: compute macd series using short slices
    macd_series = []
    for i in range(len(closes) - slow - 1, len(closes)):
        slice_ = closes[:i + 1]
        if len(slice_) < slow:
            continue
        val = ema(slice_[-(slow + 5):], fast) - ema(slice_[-(slow + 5):], slow)
        macd_series.append(val)
    if not macd_series:
        return (None, None, None)
    signal_line = ema(macd_series, signal)
    histogram = None
    if macd_line is not None and signal_line is not None:
        histogram = macd_line - signal_line
    return (macd_line, signal_line, histogram)


def _is_uptrend(closes, ma_short=MA_SHORT, ma_long=MA_LONG):
    if len(closes) < ma_long:
        return False
    sma_short = _sma(closes[-ma_short:])
    sma_long = _sma(closes[-ma_long:])
    return sma_short is not None and sma_long is not None and sma_short > sma_long


def decide_trade(filing: Dict, broker: AlpacaBroker) -> Optional[Dict]:
    # Only consider after insider buys — user expects this to complement insider strategy
    if filing.get("form") != "4":
        return None
    symbol = filing.get("ticker")
    if not symbol:
        return None

    # fetch daily bars (we'll use Alpaca REST via broker.api where possible)
    try:
        bars = broker.api.get_barset(symbol, 'day', limit=252)[symbol]
    except Exception:
        return None
    closes = [b.c for b in bars if getattr(b, 'c', None) is not None]
    if len(closes) < MA_LONG:
        return None

    # basic liquidity guard
    adv = broker.avg_daily_volume(symbol)
    if adv is not None and adv < MIN_AVG_DAILY_VOLUME:
        return None

    # price above MA_CONFIRM_SHORT
    price = broker.current_price(symbol)
    ma_long = _sma(closes[-MA_LONG:])
    if price is None or ma_long is None or price < ma_long:
        return None

    # compute indicators
    rsi_val = _rsi(closes)
    if rsi_val is None or not (MIN_RSI <= rsi_val <= MAX_RSI):
        return None

    macd_line, signal_line, hist = _macd(closes)
    if hist is None or hist <= 0:
        return None

    # moving average crossover confirmation
    if not _is_uptrend(closes):
        return None

    # multi-timeframe confirmation: use weekly and monthly by sampling daily closes
    # weekly: last 5 trading days trend; monthly: last ~21 trading days
    tf_up = 0
    try:
        # 1D already checked via MA and MACD
        tf_up += 1
        # 1W check: compare 5-day SMA vs 50-day SMA
        if len(closes) >= 50:
            sma_5 = _sma(closes[-5:])
            sma_50 = _sma(closes[-50:])
            if sma_5 and sma_50 and sma_5 > sma_50:
                tf_up += 1
        # 1M check: 21-day vs 50-day
        if len(closes) >= 50:
            sma_21 = _sma(closes[-21:])
            sma_50 = _sma(closes[-50:])
            if sma_21 and sma_50 and sma_21 > sma_50:
                tf_up += 1
    except Exception:
        pass

    if tf_up < MULTI_TF_REQUIRED:
        return None

    # sector performance and Fama-French: placeholders — return None if unavailable, otherwise continue
    # If you have sector data or factor time series, we can include a regression here. For now we skip this gate.

    qty = dollar_position(price)
    if qty == 0:
        return None

    return {"action": "BUY", "symbol": symbol, "qty": qty, "entry_price": price}
