# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Python algorithmic equity trading bot, evolving into a small "mini quant platform": event-driven engine, pluggable signal sources, auto-discovered strategies, Alpaca for execution. Currently paper-trading. Two strategies implemented (`insider_simple`, `momentum`), both filing-driven. The README is one-paragraph; the real context is here.

> **Two cores exist right now.** `bot/core` + `bot/main` (threads/queue, equities/filing, polling) is the **legacy** prototype. `bot/framework/` is the **new** asyncio, multi-asset, mode-agnostic core (see `docs/framework-design.md`). Control it from **`control.py`** (the knob panel: `ENABLED`, `MODE` sim/paper/live, `STRATEGIES` with per-strategy on/off) and launch with **`python -m bot.run {backtest|live}`**. New work goes in `bot/framework/`; the legacy core is kept only until fully superseded, then it can be deleted. The practice strategies were intentionally not ported. Don't cross-wire the two.

## Run / develop

```bash
# Always work inside the venv (Python 3.13).
source .venv/bin/activate

# Start the bot — boots the engine, discovers strategies, runs forever.
python -m bot.main

# Recreate the venv from scratch (e.g. after a clean clone):
python3.13 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

Runtime env vars (read via `python-dotenv` from `.env`; see `.env.example`):
- `ALPACA_KEY_ID`, `ALPACA_SECRET_KEY`, `ALPACA_BASE_URL` — paper or live.
- `SEC_USER_AGENT` — SEC requires a real email in the User-Agent for the EDGAR feed.
- `ALPACA_DATA_FEED` (default `iex`) — `iex` is free + 15-min delayed; `sip` needs a paid market-data subscription.
- `POLL_INTERVAL` (default 180s) — controls both EDGAR polling and the TICK clock that drives exit checks.
- `DISABLED_STRATEGIES` — comma-separated `name`s to disable without removing them. Useful when running the bot during code changes so it can't accidentally place paper orders.
- `LOG_LEVEL` — defaults to INFO.

There is no test suite yet (`tests/` is empty). The standard "is this working" check is a smoke import + paper-account read:

```bash
.venv/bin/python -c "
from bot.core.registry import discover_strategies
from bot.brokers.alpaca import AlpacaBroker
print('strategies:', [s.name for s in discover_strategies()])
print('equity:', AlpacaBroker(paper=True).account_info().equity)
"
```

## Architecture (big picture — spans many files)

The codebase is event-driven with three layers; understanding this is the prerequisite for any non-trivial change.

```
sources (threads)            engine (1 consumer)
 EdgarSource ──┐   Event      queue.get()
 ClockSource ──┼──────────▶     → dispatch to subscribed strategies
 AlpacaStream ─┘                → execute Orders (broker calls live here)
                                → run exits on TICK
```

1. **`bot/sources/`** — `SignalSource` subclasses run in their own threads and emit normalized `Event`s onto a queue. `EdgarSource` polls SEC and owns its own dedup (writes `state/seen.json`). `ClockSource` emits a `TICK` every `POLL_INTERVAL` — this is what drives periodic exit evaluation. `AlpacaStreamSource` is the real-time websocket path; **off by default**, enable in `main.py` once you have a strategy subscribing to BAR/QUOTE/TRADE.

2. **`bot/core/`** — `events.py` (Event + Order + EventType enum), `strategy.py` (Strategy ABC: `name`, `subscribes`, `on_event(event, broker) -> Order | None`), `registry.py` (auto-discovery: walks `bot.strategies` and instantiates every concrete Strategy subclass), `engine.py` (the consumer loop: routes events to subscribed strategies, owns execution + position bookkeeping + exits).

3. **`bot/strategies/<category>/`** — categories are `regular/`, `prediction_markets/`, `commodities/`, `blockchain_crypto/`. Adding a strategy = drop a file containing a `Strategy` subclass into any category subpackage. No edits to `main.py`, `engine.py`, or any registry list — discovery is automatic. The `regular/` strategies retain a free-function `decide_trade(filing, broker)` wrapped by a thin `Strategy` class; new strategies don't need this two-layer split (it exists for backward compatibility).

**The strategy contract is strict**: a Strategy *only* decides. It never submits orders, never reads/writes `state/open_positions.json`, never checks exits, never calls `log_trade`. The engine owns those. This is the seam that lets you swap broker or risk policy without touching strategies, and lets you add new event types (price streams, alt-data feeds) without rewriting decision logic.

**Exit logic is centralized** in `bot/risk/exit.py` (`STOP_PCT`, `PROFIT_PCT`, `MAX_DAYS`). The engine evaluates exits on every `TICK`; strategies have no input. Position state is JSON files in `state/` (`open_positions.json`, `seen.json`); trade/exit history is CSV in `logs/` (`trades.csv`, `closed_trades.csv`).

**Sizing**: `bot/risk/size.py::dollar_position` targets ~$100/trade and **returns 0 for any stock priced > $100/share**, silently excluding high-priced names. This is intentional but easy to miss — change `TARGET_DOLLARS` if you broaden the universe.

`ui/` is a separate FastAPI-style backend scaffold (backtest/payoff/strategies/trades routes). It is **not wired into the live bot loop** — treat it as independent until told otherwise.

## Project-specific gotchas

These are non-obvious and have already bitten this codebase:

- **alpaca-trade-api v3.x changed names.** Do not use `get_barset` (removed) or `q.bidprice`/`q.askprice` (renamed). Use `api.get_bars(symbol, TimeFrame.X, start=..., end=..., feed=...)` — bars require an **explicit date window** or return `[]` silently. Quote entities expose `.bid_price`/`.ask_price`; trade entities expose `.price`. The broker (`bot/brokers/alpaca.py`) wraps all of this — prefer adding helpers there rather than calling `broker.api` directly from strategies.

- **IEX (free) data is ~15 min delayed and has wide stale spreads.** The broker's `_DATA_DELAY` pads request windows. The current `MAX_SPREAD_DOLLARS = 0.05` filter in `insider_simple` will reject almost everything on IEX (live spread on AAPL came back at ~$30 in testing). Loosen for paper or move to SIP for realistic quotes.

- **Python 3.10+ is required** (codebase uses PEP 604 `X | None`). The pinned `numpy==2.2.6` is the lowest with a Python 3.13 wheel — bumping Python *down* will break the install. `pandas` is pinned at `2.3.1` deliberately to avoid the pandas 3.0 behavioral changes.

- **Datetimes are timezone-aware (`datetime.now(timezone.utc)`).** `state/open_positions.json` stores ISO strings with offset; `bot/risk/exit.py` compares aware↔aware. Don't reintroduce `datetime.utcnow()` — naive vs aware will raise on subtraction.

- **Do not put the project under `~/Desktop/`.** macOS "Desktop & Documents in iCloud" silently evicts `.venv` files mid-session (pip itself disappeared during a prior session). The project was moved to `~/Projects/goat-trading-bot` to escape this. If `ModuleNotFoundError` appears after a working install, this is the cause.

- **`python -m bot.main` runs forever** (3-min polling loop with daemon threads). For any verification that doesn't need to place orders, set `DISABLED_STRATEGIES=insider_simple,momentum` so an EDGAR poll mid-test cannot fire a paper order.

- **`get_latest_trade` works with the default feed**, but `get_latest_quote` and `get_bars` should be called with `feed=self.feed` (default `iex`) for free-tier accounts. The broker already does this.
