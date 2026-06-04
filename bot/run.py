# bot/run.py
"""The single launcher. Reads `control.py` and runs the enabled strategies.

    python -m bot.run backtest                 # replay history through SimBroker
    python -m bot.run live                      # live data; SimBroker/paper/live per MODE
    python -m bot.run backtest --venue kalshi   # pick a venue explicitly
    python -m bot.run backtest --start 2024-01-01 --end 2024-12-31 --timeframe 1Day

A run targets ONE venue (equities or prediction markets); all enabled strategies
for that venue run concurrently against one shared book. The venue plugin
(`bot/framework/venues/`) supplies the data source, specs, and broker — the
launcher stays venue-agnostic. Backtests always use SimBroker regardless of MODE.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal

import control
from bot.framework.assembly import build_engine
from bot.framework.sources import ClockSource
from bot.framework.venues import get_venue

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("bot.run")


def _select_strategies(venue_arg: str | None):
    """Enabled strategies for the chosen venue (inferred if a single venue, else
    requires --venue)."""
    enabled = [s for s in control.STRATEGIES if s.enabled]
    if not enabled:
        raise SystemExit("no enabled strategies in control.py")
    venues = {s.venue for s in enabled}
    venue = venue_arg or (venues.pop() if len(venues) == 1 else None)
    if venue is None:
        raise SystemExit(f"enabled strategies span venues {sorted(venues)}; "
                         f"pick one with --venue")
    chosen = [s for s in enabled if s.venue == venue]
    if not chosen:
        raise SystemExit(f"no enabled strategies for venue {venue!r}")
    symbols = sorted({sym for s in chosen for sym in s.symbols})
    return venue, chosen, symbols


# --- live -------------------------------------------------------------------
async def _run_live(venue_arg: str | None) -> None:
    venue_name, strategies, symbols = _select_strategies(venue_arg)
    venue = get_venue(venue_name)
    log.info("LIVE | venue=%s mode=%s | strategies=%s | universe=%s",
             venue_name, control.MODE.value, [s.name for s in strategies], symbols)

    source, specs = venue.live_setup(symbols, control.MODE)
    broker = venue.make_broker(control.MODE, {s.symbol: s for s in specs},
                               control.CONFIG.starting_cash)
    clock = ClockSource(control.CONFIG.decision_interval_seconds)
    engine = build_engine(control.CONFIG, specs, sources=[source, clock],
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
async def _run_backtest(args) -> None:
    from bot.framework.replay import ReplaySource

    venue_name, strategies, symbols = _select_strategies(args.venue)
    venue = get_venue(venue_name)
    bt = {**control.BACKTEST}
    if args.start: bt["start"] = args.start
    if args.end: bt["end"] = args.end
    if args.timeframe: bt["timeframe"] = args.timeframe

    log.info("BACKTEST | venue=%s %s %s..%s | strategies=%s | universe=%s",
             venue_name, bt["timeframe"], bt["start"], bt["end"],
             [s.name for s in strategies], symbols)

    events, specs, decision_interval = venue.backtest_setup(
        symbols, bt["start"], bt["end"], bt["timeframe"])
    if not events:
        raise SystemExit("no bars to replay — check symbols/dates/credentials.")

    source = ReplaySource(events, decision_interval=decision_interval)
    engine = build_engine(control.CONFIG, specs, sources=[source],
                          strategies=strategies, run_id="backtest")  # SimBroker
    await engine.run()

    from scripts.analyze import summarize
    summarize("logs/equity_backtest.csv", fills_path="logs/fills_backtest.csv")


def main() -> None:
    parser = argparse.ArgumentParser(prog="bot.run")
    sub = parser.add_subparsers(dest="cmd", required=True)
    live = sub.add_parser("live")
    live.add_argument("--venue")
    bt = sub.add_parser("backtest")
    bt.add_argument("--venue")
    bt.add_argument("--start")
    bt.add_argument("--end")
    bt.add_argument("--timeframe")
    args = parser.parse_args()

    if not control.ENABLED:
        raise SystemExit("control.ENABLED is False — the bot is switched off.")

    if args.cmd == "live":
        asyncio.run(_run_live(args.venue))
    else:
        asyncio.run(_run_backtest(args))


if __name__ == "__main__":
    main()
