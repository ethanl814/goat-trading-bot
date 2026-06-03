# control.py — THE KNOB PANEL
# ============================================================================
# This is the one file you edit to control the bot. Flip strategies on/off,
# switch sim/paper/live, set the universe and risk. Then run:
#
#     python -m bot.run backtest      # replay history through enabled strategies
#     python -m bot.run live          # run enabled strategies on live data
#
# Nothing here routes real-money orders unless MODE = LIVE *and* you set the
# env var ALLOW_LIVE_TRADING=yes (a deliberate two-step safety).
# ============================================================================
from bot.framework.config import RunConfig, StrategySpec
from bot.framework.modes import TradingMode
from bot.framework.risk import RiskLimits

# --- master switches --------------------------------------------------------
ENABLED = True                       # global kill switch for the whole bot
MODE = TradingMode.SIM               # SIM (fake fills) | PAPER (Alpaca paper) | LIVE ($$$)

# --- book-level config (shared by all strategies) ---------------------------
CONFIG = RunConfig(
    starting_cash=100_000.0,
    decision_interval_seconds=60.0,  # how often the allocator step runs (live)
    risk=RiskLimits(
        gross_cap_frac=1.5,
        net_cap_frac=1.0,
        max_drawdown_frac=0.20,      # kill switch trips here
    ),
)

# --- strategies: flip `enabled` to turn each on/off -------------------------
# A strategy = a registered signal + its params + a universe + sizing. Add one
# by appending a StrategySpec (and, if it's a new signal, dropping a Signal
# subclass into bot/framework/signals/). No engine edits.
STRATEGIES = [
    StrategySpec(
        name="reversion-tech",
        signal="reversion",
        enabled=True,
        symbols=["AAPL", "MSFT", "NVDA", "AMD", "INTC"],
        signal_params={"window": 20},
        capital_frac=1.0,
    ),
    StrategySpec(
        name="reversion-slow",
        signal="reversion",
        enabled=False,               # ← toggle me on to run alongside the above
        symbols=["AAPL", "MSFT", "GOOGL", "AMZN", "META"],
        signal_params={"window": 60},
        capital_frac=0.5,
    ),
]

# --- backtest window (used by `python -m bot.run backtest`) -----------------
BACKTEST = {
    "start": "2024-01-01",
    "end": "2024-12-31",
    "timeframe": "1Day",             # 1Day | 1Hour | 1Min
    "synthetic": False,              # True = random-walk data (no API/creds needed)
}
