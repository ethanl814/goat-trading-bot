# scripts/backtest_sports_fade.py
"""Cost-aware backtest for the in-game run-reversal fade (RunReversalFade).

Pipeline: discover liquid SETTLED single-game markets -> fetch each market's
minute candles + settlement -> replay through the real engine with the realistic
Kalshi cost model -> print a trade-level + aggregate report (incl. fee/spread drag).

    python -m scripts.backtest_sports_fade                       # taker, default params
    python -m scripts.backtest_sports_fade --mode maker          # assume limit fills (optimistic)
    python -m scripts.backtest_sports_fade --entry-drop 0.18 --conviction
    python -m scripts.backtest_sports_fade --avoid 0.45 0.55     # skip the p~0.5 fee peak
    python -m scripts.backtest_sports_fade --series KXATPMATCH --n 40

Modes:
  taker  — cross the spread (half_spread per fill) + Kalshi taker fee (0.07).
  maker  — rest at price (NO spread) + a maker-fee assumption (default 0).
           ⚠️ optimistic: assumes your limit order fills.

NBA single-game markets only exist in-season; this validates the *mechanism* on
liquid tennis matches (same momentum-swing dynamic) and is sport-agnostic. The
reusable `run_backtest()` powers `scripts/sweep_sports_fade.py`.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import timedelta

from bot.framework.assembly import build_engine
from bot.framework.config import RunConfig, StrategySpec
from bot.framework.replay import ReplaySource
from bot.framework.venues.kalshi.adapter import build_spec
from bot.framework.venues.kalshi.client import KalshiClient, to_float
from bot.framework.venues.kalshi.history import fetch_game_window

# Single-EVENT win markets (one market per side, with intra-event price history),
# the thesis analog. KXNBA-26-* are championship FUTURES, not games — excluded.
DEFAULT_GAME_SERIES = ("KXATPMATCH", "KXITFMATCH", "KXITFWMATCH", "KXWTACHALLENGERMATCH")


def discover_tickers(client, n, status, series_csv=None):
    series_list = series_csv.split(",") if series_csv else DEFAULT_GAME_SERIES
    pooled = []
    for series in series_list:
        try:
            pooled.extend(client.get_markets(series_ticker=series, status=status, limit=200).get("markets", []))
        except Exception:
            continue
    pooled.sort(key=lambda m: to_float(m.get("volume_fp")) or 0, reverse=True)
    return [m["ticker"] for m in pooled[:n]]


def load_events(client, tickers, window_hours=24):
    return fetch_game_window(tickers, client=client, lookback_hours=window_hours)


def run_backtest(tickers, events, *, signal_params, contracts=100, scale_by_conviction=False,
                 conviction_cap=3.0, half_spread=0.01, fee_coefficient=0.07, cash=10_000.0) -> dict:
    """Run one configuration and return metrics. Reusable across the sweep."""
    specs = [build_spec(t, fee_coefficient=fee_coefficient, half_spread=half_spread) for t in tickers]
    strat = [StrategySpec(name="run-fade", venue="kalshi", signal="run_fade", symbols=tickers,
                          signal_params=signal_params, allocator="event_fade", contracts=contracts,
                          scale_by_conviction=scale_by_conviction, conviction_cap=conviction_cap)]
    cfg = RunConfig(starting_cash=cash, decision_interval_seconds=60)
    engine = build_engine(cfg, specs, sources=[ReplaySource(events, decision_interval=timedelta(minutes=1))],
                          strategies=strat, record=False)
    signals = [sig for s in engine.strategies for sig in s.signals.values()]
    n_markets = len(signals)
    asyncio.run(engine.run())

    trades = [t for sig in signals for t in sig.trades]
    held = sum(1 for sig in signals if sig.state == "LONG")
    equity = engine.broker.equity(engine.states)
    gross = engine.broker.realized
    by_reason: dict[str, int] = {}
    for t in trades:
        by_reason[t["reason"]] = by_reason.get(t["reason"], 0) + 1
    wins = sum(1 for t in trades if t["move"] > 0)
    return {
        "n_markets": n_markets, "n_trades": len(trades), "held": held, "trades": trades,
        "net": equity - cash, "gross": gross, "cost_drag": gross - (equity - cash),
        "equity": equity, "by_reason": by_reason,
        "win_rate": wins / len(trades) if trades else 0.0,
        "avg_move": sum(t["move"] for t in trades) / len(trades) if trades else 0.0,
    }


def _report(r, cash, params, mode):
    print("\n" + "=" * 64)
    print(f"  IN-GAME RUN-REVERSAL FADE — BACKTEST ({mode})")
    print("=" * 64)
    print(f"  params: {params}")
    print(f"  markets traded     : {r['n_markets']}")
    print(f"  fade trades (exited): {r['n_trades']}  (+{r['held']} held to resolution)")
    if r["n_trades"]:
        print(f"  exit reasons       : {r['by_reason']}")
        print(f"  win rate (decision): {r['win_rate']*100:.1f}%")
        print(f"  avg move/trade     : {r['avg_move']*100:+.2f} cents (before costs)")
    print("-" * 64)
    print(f"  starting cash      : ${cash:,.2f}")
    print(f"  final equity       : ${r['equity']:,.2f}")
    print(f"  NET P&L (after costs)        : ${r['net']:,.2f}")
    print(f"  gross price P&L (realized)   : ${r['gross']:,.2f}")
    print(f"  cost drag (fees+slippage)    : ${r['cost_drag']:,.2f}")
    print("=" * 64)
    for t in r["trades"][:8]:
        print(f"    {t['instrument'][:34]:34} {t['entry']:.2f} -> {t['exit']:.2f} "
              f"({t['reason']}, conv {t['conviction']}, {t['move']*100:+.1f}c)")


def main():
    p = argparse.ArgumentParser(prog="backtest_sports_fade")
    p.add_argument("--tickers", help="comma-separated tickers (else auto-discover)")
    p.add_argument("--n", type=int, default=30)
    p.add_argument("--series", help="comma-separated series (else liquid tennis matches)")
    p.add_argument("--status", default="settled")
    p.add_argument("--env", default="prod")
    p.add_argument("--window-hours", type=int, default=24)
    p.add_argument("--cash", type=float, default=10_000.0)
    p.add_argument("--mode", choices=("taker", "maker"), default="taker")
    p.add_argument("--half-spread", type=float, default=0.01, help="taker spread per fill")
    p.add_argument("--maker-fee", type=float, default=0.0, help="maker fee coefficient (assumption)")
    p.add_argument("--contracts", type=int, default=100)
    p.add_argument("--conviction", action="store_true", help="size ∝ overreaction magnitude")
    # signal knobs
    p.add_argument("--lookback", type=int, default=4)
    p.add_argument("--entry-drop", type=float, default=0.15)
    p.add_argument("--min-drop-per-bar", type=float, default=0.0)
    p.add_argument("--reversion-frac", type=float, default=0.5)
    p.add_argument("--stop-drop", type=float, default=0.10)
    p.add_argument("--max-hold", type=int, default=15)
    p.add_argument("--avoid", nargs=2, type=float, metavar=("LO", "HI"), default=(0.0, 0.0),
                   help="skip entries with price in (LO,HI) to dodge the p~0.5 fee peak")
    args = p.parse_args()

    client = KalshiClient(env=args.env)
    tickers = args.tickers.split(",") if args.tickers else discover_tickers(client, args.n, args.status, args.series)
    if not tickers:
        raise SystemExit("no single-game markets found — pass --tickers or --series")
    print(f"backtesting {len(tickers)} markets (status={args.status}, mode={args.mode}) ...")
    events = load_events(client, tickers, args.window_hours)
    if not events:
        raise SystemExit("no candle data returned")

    sig_params = dict(lookback=args.lookback, entry_drop=args.entry_drop,
                      min_drop_per_bar=args.min_drop_per_bar, reversion_frac=args.reversion_frac,
                      stop_drop=args.stop_drop, max_hold=args.max_hold,
                      avoid_lo=args.avoid[0], avoid_hi=args.avoid[1])
    half_spread = args.half_spread if args.mode == "taker" else 0.0
    fee_coef = 0.07 if args.mode == "taker" else args.maker_fee
    r = run_backtest(tickers, events, signal_params=sig_params, contracts=args.contracts,
                     scale_by_conviction=args.conviction, half_spread=half_spread,
                     fee_coefficient=fee_coef, cash=args.cash)
    _report(r, args.cash, sig_params, args.mode)


if __name__ == "__main__":
    main()
