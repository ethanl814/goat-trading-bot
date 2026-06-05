# scripts/backtest_sports_fade.py
"""Cost-aware backtest for the in-game run-reversal fade (RunReversalFade).

Pipeline:
  1. discover liquid SETTLED single-game markets (default) — they have intra-game
     minute price history AND a known outcome;
  2. fetch each market's minute candles + settlement (`fetch_game_window`);
  3. replay them through the real engine with RunReversalFade + EventFadeAllocator
     and the realistic Kalshi cost model (fees + half-spread);
  4. print a trade-level + aggregate report, and the fee/slippage drag.

    python -m scripts.backtest_sports_fade                       # auto-discover tennis/games
    python -m scripts.backtest_sports_fade --n 40 --half-spread 0.02
    python -m scripts.backtest_sports_fade --tickers T1,T2,...    # specific markets
    python -m scripts.backtest_sports_fade --entry-drop 0.10 --reversion-frac 0.5 --max-hold 20

NBA is the thesis target, but single-game NBA markets only exist in-season; this
validates the *mechanism* on whatever liquid single-game markets exist now
(tennis matches show the same momentum-swing dynamic). It is sport-agnostic.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import timedelta

from bot.framework.assembly import build_engine
from bot.framework.config import RunConfig, StrategySpec
from bot.framework.replay import ReplaySource
from bot.framework.venues.kalshi.adapter import build_spec
from bot.framework.venues.kalshi.client import KalshiClient
from bot.framework.venues.kalshi.discover import liquid_markets
from bot.framework.venues.kalshi.history import fetch_game_window

# Single-EVENT win markets (one market per side, with intra-event price history).
# These are the thesis analog: a tennis match's win-prob swings on momentum just
# like an NBA game's does on a run. NBA single-GAME markets (when in season) slot
# in here too; KXNBA-26-* are championship FUTURES, not games — don't use those.
DEFAULT_GAME_SERIES = ("KXATPMATCH", "KXITFMATCH", "KXITFWMATCH", "KXWTACHALLENGERMATCH")


def _discover_game_tickers(client, n, status, series_csv=None):
    from bot.framework.venues.kalshi.client import to_float
    series_list = series_csv.split(",") if series_csv else DEFAULT_GAME_SERIES
    pooled = []
    for series in series_list:
        try:
            ms = client.get_markets(series_ticker=series, status=status, limit=200).get("markets", [])
        except Exception:
            continue
        pooled.extend(ms)
    pooled.sort(key=lambda m: to_float(m.get("volume_fp")) or 0, reverse=True)
    return [m["ticker"] for m in pooled[:n]]


def _report(signals, n_markets, engine, cfg, params):
    # `signals` is captured BEFORE the run (the engine pops them on resolution).
    trades = [t for sig in signals for t in getattr(sig, "trades", [])]
    held_to_resolution = sum(1 for sig in signals if getattr(sig, "state", "FLAT") == "LONG")

    equity = engine.broker.equity(engine.states)
    net_pnl = equity - cfg.starting_cash
    gross_pnl = engine.broker.realized  # price PnL gross of fees/slippage

    print("\n" + "=" * 64)
    print("  IN-GAME RUN-REVERSAL FADE — BACKTEST")
    print("=" * 64)
    print(f"  params: {params}")
    print(f"  markets traded     : {n_markets}")
    print(f"  fade trades (exited): {len(trades)}  (+{held_to_resolution} held to resolution)")
    if trades:
        by_reason = {}
        for t in trades:
            by_reason[t["reason"]] = by_reason.get(t["reason"], 0) + 1
        wins = sum(1 for t in trades if t["move"] > 0)
        avg_move = sum(t["move"] for t in trades) / len(trades)
        print(f"  exit reasons       : {by_reason}")
        print(f"  win rate (decision): {wins}/{len(trades)} = {wins/len(trades)*100:.1f}%")
        print(f"  avg move/trade     : {avg_move*100:+.2f} cents (before costs)")
    print("-" * 64)
    print(f"  starting cash      : ${cfg.starting_cash:,.2f}")
    print(f"  final equity       : ${equity:,.2f}")
    print(f"  NET P&L (after fees+slippage): ${net_pnl:,.2f}")
    print(f"  gross price P&L (realized)   : ${gross_pnl:,.2f}")
    print(f"  cost drag (fees+slippage)    : ${gross_pnl - net_pnl:,.2f}")
    print("=" * 64)
    if trades[:8]:
        print("  sample trades (entry -> exit, reason):")
        for t in trades[:8]:
            print(f"    {t['instrument'][:34]:34} {t['entry']:.2f} -> {t['exit']:.2f} "
                  f"({t['reason']}, {t['bars_held']}b, {t['move']*100:+.1f}c)")


async def _run(args):
    client = KalshiClient(env=args.env)
    if args.tickers:
        tickers = args.tickers.split(",")
    else:
        tickers = _discover_game_tickers(client, args.n, args.status, args.series)
    if not tickers:
        raise SystemExit("no single-game markets found — pass --tickers, or try --status settled")
    print(f"backtesting {len(tickers)} markets (status={args.status}) ...")

    events = fetch_game_window(tickers, client=client, lookback_hours=args.window_hours)
    if not events:
        raise SystemExit("no candle data returned for these markets")

    specs = [build_spec(t, half_spread=args.half_spread) for t in tickers]
    sig_params = dict(lookback=args.lookback, entry_drop=args.entry_drop,
                      reversion_frac=args.reversion_frac, stop_drop=args.stop_drop,
                      max_hold=args.max_hold)
    strat = [StrategySpec(name="run-fade", venue="kalshi", signal="run_fade",
                          symbols=tickers, signal_params=sig_params,
                          allocator="event_fade", contracts=args.contracts)]
    cfg = RunConfig(starting_cash=args.cash, decision_interval_seconds=60)
    engine = build_engine(cfg, specs, sources=[ReplaySource(events, decision_interval=timedelta(minutes=1))],
                          strategies=strat, record=False)
    # capture signal instances now — the engine pops them from the dict on resolution
    signals = [sig for s in engine.strategies for sig in s.signals.values()]
    n_markets = len(signals)
    await engine.run()
    _report(signals, n_markets, engine, cfg, sig_params)


def main():
    p = argparse.ArgumentParser(prog="backtest_sports_fade")
    p.add_argument("--tickers", help="comma-separated market tickers (else auto-discover)")
    p.add_argument("--n", type=int, default=25, help="markets to discover")
    p.add_argument("--series", help="comma-separated series tickers (else liquid tennis matches)")
    p.add_argument("--status", default="settled", help="settled (best) | open")
    p.add_argument("--env", default="prod")
    p.add_argument("--window-hours", type=int, default=24)
    p.add_argument("--cash", type=float, default=10_000.0)
    p.add_argument("--contracts", type=int, default=100)
    p.add_argument("--half-spread", type=float, default=0.01, help="slippage per fill (prob units)")
    # signal knobs
    p.add_argument("--lookback", type=int, default=5)
    p.add_argument("--entry-drop", type=float, default=0.08)
    p.add_argument("--reversion-frac", type=float, default=0.5)
    p.add_argument("--stop-drop", type=float, default=0.10)
    p.add_argument("--max-hold", type=int, default=15)
    asyncio.run(_run(p.parse_args()))


if __name__ == "__main__":
    main()
