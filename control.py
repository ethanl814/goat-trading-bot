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
    # --- equities (Alpaca) --------------------------------------------------
    StrategySpec(
        name="reversion-tech",
        venue="alpaca",
        signal="reversion",
        enabled=True,
        symbols=["AAPL", "MSFT", "NVDA", "AMD", "INTC"],
        signal_params={"window": 20},
        allocator="cross_sectional",
        capital_frac=1.0,
    ),
    StrategySpec(
        name="reversion-slow",
        venue="alpaca",
        signal="reversion",
        enabled=False,               # ← toggle on to run alongside the above
        symbols=["AAPL", "MSFT", "GOOGL", "AMZN", "META"],
        signal_params={"window": 60},
        allocator="cross_sectional",
        capital_frac=0.5,
    ),

    # --- prediction markets (Kalshi) ---------------------------------------
    # Fill `symbols` with real Kalshi market tickers (e.g. from get_markets), and
    # swap `signal` for your own thesis (subclass ProbabilityReversion, override
    # fair_value). Threshold allocator = per-contract trigger on the edge z-score.
    StrategySpec(
        name="kalshi-thesis",
        venue="kalshi",
        signal="prob_reversion",
        enabled=False,               # ← needs real tickers; turn on to trade Kalshi
        symbols=[],                  # e.g. ["KXBTCD-25DEC3117-T100000", ...]
        signal_params={"window": 30},
        allocator="threshold",
        entry_z=1.0,
        per_name_frac=0.05,
        capital_frac=1.0,
    ),

    # In-game run-reversal fade (see docs/strategies/sports-run-fade.md).
    # Backtest-profitable in the BIG/RARE-overreaction regime: taker +3% with
    # conviction + fee-peak avoidance, maker +8.7%. Params below are the validated
    # taker config. To deploy: put today's single-game tickers in `symbols`, set
    # enabled=True, start in MODE=PAPER (Kalshi demo). For in-game speed also drop
    # CONFIG.decision_interval_seconds to ~5.
    StrategySpec(
        name="run-reversal-fade",
        venue="kalshi",
        signal="run_fade",
        enabled=False,               # ← set True + add symbols to deploy
        symbols=[],                  # live single-game win-market tickers
        signal_params={"lookback": 4, "entry_drop": 0.22, "reversion_frac": 0.4,
                       "stop_drop": 0.10, "max_hold": 15,
                       "avoid_lo": 0.42, "avoid_hi": 0.58},  # dodge the p~0.5 fee peak
        allocator="event_fade",
        contracts=100,
        scale_by_conviction=True,    # bet more on bigger overreactions
        conviction_cap=3.0,
    ),
]

# --- backtest window (used by `python -m bot.run backtest`) -----------------
BACKTEST = {
    "start": "2024-01-01",
    "end": "2024-12-31",
    "timeframe": "1Day",             # 1Day | 1Hour | 1Min
}
