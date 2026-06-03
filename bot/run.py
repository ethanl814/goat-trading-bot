# bot/run.py
"""The single launcher. Reads `control.py` and runs the enabled strategies.

    python -m bot.run backtest      # replay history (or synthetic) through SimBroker
    python -m bot.run live          # live data; SimBroker / paper / live per control.MODE

Backtest always uses simulated fills regardless of MODE — you don't route orders
at historical prices. Live honors `control.MODE` (sim fills / Alpaca paper / real).
CLI flags override control.py for one run, e.g.:

    python -m bot.run backtest --start 2023-01-01 --end 2023-06-30 --timeframe 1Day
    python -m bot.run backtest --synthetic
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
from datetime import timedelta

import control
from bot.framework.assembly import build_engine
from bot.framework.instruments import AssetClass, InstrumentSpec, PriceKind
from bot.framework.modes import TradingMode, make_broker, make_data_broker
from bot.framework.replay import ReplaySource, generate_synthetic_bars
from bot.framework.sources import ClockSource

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("bot.run")

_TF_DELTA = {"1Day": timedelta(days=1), "1Hour": timedelta(hours=1), "1Min": timedelta(minutes=1)}


def _enabled_strategies():
    strs = [s for s in control.STRATEGIES if s.enabled]
    if not strs:
        raise SystemExit("no enabled strategies in control.py")
    return strs


def _union_symbols(strategies) -> list[str]:
    return sorted({sym for s in strategies for sym in s.symbols})


# --- live -------------------------------------------------------------------
async def _run_live() -> None:
    from bot.framework.adapters.equities_alpaca import EquitiesAlpacaAdapter

    strategies = _enabled_strategies()
    symbols = _union_symbols(strategies)
    log.info("LIVE | mode=%s | strategies=%s | universe=%s",
             control.MODE.value, [s.name for s in strategies], symbols)

    adapter = EquitiesAlpacaAdapter(symbols, subscribe=("trades", "quotes"),
                                    broker=make_data_broker(control.MODE))
    specs = adapter.build_specs(symbols)
    spec_map = {s.symbol: s for s in specs}
    broker = make_broker(control.MODE, spec_map, control.CONFIG.starting_cash)
    clock = ClockSource(control.CONFIG.decision_interval_seconds)

    engine = build_engine(control.CONFIG, specs, sources=[adapter, clock],
                          strategies=strategies, broker=broker)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            pass
    await engine.run(stop)


# --- backtest ---------------------------------------------------------------
def _backtest_specs(symbols: list[str]) -> list[InstrumentSpec]:
    return [InstrumentSpec(symbol=s, asset_class=AssetClass.EQUITY,
                           price_kind=PriceKind.CONTINUOUS, slippage_bps=2.0)
            for s in symbols]


async def _run_backtest(args) -> None:
    strategies = _enabled_strategies()
    symbols = _union_symbols(strategies)
    bt = {**control.BACKTEST}
    if args.start: bt["start"] = args.start
    if args.end: bt["end"] = args.end
    if args.timeframe: bt["timeframe"] = args.timeframe
    if args.synthetic: bt["synthetic"] = True

    tf = bt["timeframe"]
    if bt["synthetic"]:
        log.info("BACKTEST | synthetic data | strategies=%s | universe=%s",
                 [s.name for s in strategies], symbols)
        events = generate_synthetic_bars(symbols, n=600)
        decision_interval = timedelta(minutes=5)
    else:
        from bot.framework.history import fetch_or_load
        log.info("BACKTEST | %s %s..%s | strategies=%s | universe=%s",
                 tf, bt["start"], bt["end"], [s.name for s in strategies], symbols)
        events = fetch_or_load(symbols, bt["start"], bt["end"], timeframe=tf)
        decision_interval = _TF_DELTA.get(tf, timedelta(days=1))

    if not events:
        raise SystemExit("no bars to replay — check symbols/dates/credentials, "
                         "or run with --synthetic")

    specs = _backtest_specs(symbols)
    source = ReplaySource(events, decision_interval=decision_interval)
    engine = build_engine(control.CONFIG, specs, sources=[source],
                          strategies=strategies, run_id="backtest")  # SimBroker
    await engine.run()

    from scripts.analyze import summarize
    summarize("logs/equity_backtest.csv", fills_path="logs/fills_backtest.csv")


def main() -> None:
    parser = argparse.ArgumentParser(prog="bot.run")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("live")
    bt = sub.add_parser("backtest")
    bt.add_argument("--start")
    bt.add_argument("--end")
    bt.add_argument("--timeframe")
    bt.add_argument("--synthetic", action="store_true")
    args = parser.parse_args()

    if not control.ENABLED:
        raise SystemExit("control.ENABLED is False — the bot is switched off.")

    if args.cmd == "live":
        asyncio.run(_run_live())
    else:
        asyncio.run(_run_backtest(args))


if __name__ == "__main__":
    main()
