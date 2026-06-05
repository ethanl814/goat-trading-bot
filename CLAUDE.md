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

> ⚠️ The "Architecture (big picture)" section above describes the **legacy** `bot/core` engine. For new work use `bot/framework/` (below). The two share conventions but not code.

## Writing a signal for the framework (`bot/framework/`)

This is the part you'll touch most. A *signal* is the plug-in unit; a *strategy* is config (`StrategySpec`) that points at a signal. The full design is in `docs/framework-design.md`; the working rules:

**The `Signal` contract** (`bot/framework/signals/base.py`):
- One instance **per instrument** — the engine fans your class out to N stateful copies, one per symbol in the strategy's universe. Don't share state across symbols.
- `update(self, state, event)` must be **O(1)**. Fold the new event into rolling state (running sums, ring buffers, Welford via `RollingMeanStd`). **Never** recompute a window from scratch per tick — `tests/test_signal_equivalence.py` enforces this discipline for `RollingMeanStd`.
- `value(self)` returns a **normalized** number (a z-score / standardized signal), or `None` during warm-up. The allocator *ranks* these; it never sees a raw price or a raw % move. This is deliberate: a flat "X% move" threshold has nowhere to live.
- `applies_to` (tuple of `AssetClass`) restricts a signal to certain classes; empty = any.

**Hard rules (the seam that keeps signals portable):**
- A signal **only reads `MarketState` and emits a value**. It must **never** call the broker, submit orders, read/write position state, check exits, or log trades — the engine/allocator/risk/broker own all of that.
- Read price via `state.price()` (mid if a book exists, else last trade/close), `state.mid`, or `state.last_bar`. If you need history, keep your *own* incremental buffer; don't reach for the broker.
- Sizing, shorting, caps, and exits are **not** your concern — the `CrossSectionalAllocator` + `RiskMonitor` + `InstrumentSpec` constraints handle them generically.

**Minimal example** — drop in `bot/framework/signals/my_signal.py`:
```python
from bot.framework.signals.base import Signal
from bot.framework.registry import register
from bot.framework.state import RollingMeanStd

@register("my_momentum")              # the name you reference from control.py
class MyMomentum(Signal):
    name = "my_momentum"
    def __init__(self, instrument, spec, window=20):
        super().__init__(instrument, spec)
        self.stats = RollingMeanStd(window)
        self.prev = None
        self._value = None
    def update(self, state, event):    # O(1)
        p = state.price()
        if p is None or p <= 0:
            return
        if self.prev:
            self.stats.push((p - self.prev) / self.prev)
            if self.stats.ready and self.stats.std() > 0:
                self._value = self.stats.mean() / self.stats.std()   # momentum z-score
        self.prev = p
    def value(self):
        return self._value
```

**Turn it on** — edit `control.py` only (no engine edits):
```python
StrategySpec(name="mom-tech", signal="my_momentum", enabled=True,
             symbols=["AAPL","MSFT","NVDA"], signal_params={"window": 30})
```
Then evaluate it on real history: `python -m bot.run backtest --start 2023-01-01 --end 2023-12-31`.

**Gotchas specific to the framework:**
- `signal_params` in the `StrategySpec` are passed as `**kwargs` to your `__init__` — names must match.
- Decisions run **only on `Clock` events** (throttled), not on every tick. `update` keeps state fresh O(1); `value()` is read at the next Clock. Don't assume `value()` is consumed the instant you set it.
- The `CrossSectionalAllocator` needs ≥ `min_names` (default 2) live signal values to act, and goes long the top slice / short the bottom slice. A single-symbol universe with a cross-sectional allocator will (correctly) do nothing — use multiple names, or a `ThresholdAllocator` for per-name triggers.
- Execution is `SimBroker` in SIM/backtest; the engine is identical in paper/live (only the broker swaps). Backtests **always** use `SimBroker` regardless of `MODE`.

## Venues (multi-asset, `bot/framework/venues/`)

Each trading venue / asset class is a **self-contained package** implementing the `Venue` contract (`venues/base.py`): `live_setup`, `backtest_setup`, `_live_broker`. The launcher (`bot/run.py`) looks one up by name via the registry — the core never imports a venue. Adding a venue = drop a package with a `Venue` subclass and `register_venue(...)` in its `__init__`. A `StrategySpec.venue` field routes each strategy; a run targets one venue.

- **`venues/alpaca/`** — equities. `adapter.py` (websocket data), `broker.py` (`LiveAlpacaBroker`, scaffold), `history.py` (bars), `creds.py` (per-mode keys).
- **`venues/kalshi/`** — prediction markets. `auth.py` (RSA-PSS signing), `client.py` (REST), `adapter.py` (poll → Quote/Trade/Resolution), `history.py` (candles → Bars), `broker.py` (`LiveKalshiBroker`, scaffold).

**Writing a prediction-market thesis:** subclass `ProbabilityReversion` (`signals/edge.py`) and override `fair_value(self, state)` to return *your* model's probability; the framework standardizes the edge, triggers via `allocator="threshold"`, and computes binary-payoff PnL through `Resolution`/`SimBroker.settle`. Set `venue="kalshi"` and real tickers in `control.py`.

**First worked strategy — in-game run-reversal fade** (`signals/sports_fade.py`, `docs/strategies/sports-run-fade.md`): a per-market state-machine signal (FLAT→LONG with reversion/stop/time-stop exits), paired with `EventFadeAllocator` (discrete fixed-count enter/hold/exit so price drift doesn't churn the position). Backtest it on real single-game (tennis) minute data: `python -m scripts.backtest_sports_fade`. **Cost model matters and is now realistic:** `InstrumentSpec.fee_kind="kalshi"` charges Kalshi's actual fee (`ceil(0.07·C·p·(1−p))`, worst near p=0.5), and `slippage_price` charges crossing the spread per fill — both set by `build_spec`. The backtest's lesson (documented): the fade has a small positive *raw* edge that **does not survive taker spread + Kalshi fees** — net-negative until maker entries / bigger overreactions. When adding a discrete event-trade strategy, use `allocator="event_fade"` and let the signal own entry/exit (the allocator just sizes).

**Kalshi gotchas (verified live):**
- Auth is **RSA-PSS** (SHA256, MGF1, salt=digest len) signing `timestamp+METHOD+path` (path excludes query). Headers: `KALSHI-ACCESS-{KEY,TIMESTAMP,SIGNATURE}`. Key id + PEM path live in `.env`; the PEM itself is in `.secrets/` (git-ignored). The same key worked against **both** prod and demo in testing.
- Open markets have `status == "active"` (not `"open"`). Settled markets carry `result` = `"yes"`/`"no"` → the adapter emits `Resolution(1.0/0.0)`.
- **Candlesticks are series-scoped on the trade host**: `GET /trade-api/v2/series/{series}/markets/{ticker}/candlesticks` (series = ticker prefix before the first `-`). The `external-api.../historical/...` path only serves archived markets and 404s on active ones.
- **Candle OHLC fields are suffixed `_dollars`** (`price.close_dollars`, `yes_bid.close_dollars`, …) and volume is `volume_fp` — NOT bare `close`/`volume`. `history._field` handles both; don't "simplify" it away.
- Market prices are fixed-point **dollar strings in [0,1]** (e.g. `"0.5600"`), in fields like `yes_bid_dollars`/`last_price_dollars`. `client.to_float` parses them.
- **Backtesting a thesis: use settled markets.** `venues/kalshi/history.fetch_resolutions` appends a `Resolution` (YES→1.0/NO→0.0) at each settled market's close, so the engine settles positions at the true outcome — real binary-payoff PnL (verified: a YES resolve paid +$1 per contract through `SimBroker.settle`).
- **Finding markets:** `python -m scripts.kalshi_discover` (uses `venues/kalshi/discover.py`). `get_markets(status="open")` is flooded with auto-generated **sports parlay** markets (`KXMVE...` and per-match `KXITF*`/`KXWTA*`), so discovery filters parlays, ranks by liquidity, lists series with `--series-list`, and checks candle history with `--check TICKER`. Use `--status settled` to find backtestable markets with full history; copy the printed `symbols=[...]` into `control.py`.
- Hosts: prod trade `api.elections.kalshi.com`, demo `demo-api.kalshi.co`; overridable via `KALSHI_TRADE_HOST` / `KALSHI_ENV`.

## Project-specific gotchas

These are non-obvious and have already bitten this codebase:

- **alpaca-trade-api v3.x changed names.** Do not use `get_barset` (removed) or `q.bidprice`/`q.askprice` (renamed). Use `api.get_bars(symbol, TimeFrame.X, start=..., end=..., feed=...)` — bars require an **explicit date window** or return `[]` silently. Quote entities expose `.bid_price`/`.ask_price`; trade entities expose `.price`. The broker (`bot/brokers/alpaca.py`) wraps all of this — prefer adding helpers there rather than calling `broker.api` directly from strategies.

- **IEX (free) data is ~15 min delayed and has wide stale spreads.** The broker's `_DATA_DELAY` pads request windows. The current `MAX_SPREAD_DOLLARS = 0.05` filter in `insider_simple` will reject almost everything on IEX (live spread on AAPL came back at ~$30 in testing). Loosen for paper or move to SIP for realistic quotes.

- **Python 3.10+ is required** (codebase uses PEP 604 `X | None`). The pinned `numpy==2.2.6` is the lowest with a Python 3.13 wheel — bumping Python *down* will break the install. `pandas` is pinned at `2.3.1` deliberately to avoid the pandas 3.0 behavioral changes.

- **Datetimes are timezone-aware (`datetime.now(timezone.utc)`).** `state/open_positions.json` stores ISO strings with offset; `bot/risk/exit.py` compares aware↔aware. Don't reintroduce `datetime.utcnow()` — naive vs aware will raise on subtraction.

- **Do not put the project under `~/Desktop/`.** macOS "Desktop & Documents in iCloud" silently evicts `.venv` files mid-session (pip itself disappeared during a prior session). The project was moved to `~/Projects/goat-trading-bot` to escape this. If `ModuleNotFoundError` appears after a working install, this is the cause.

- **`python -m bot.main` runs forever** (3-min polling loop with daemon threads). For any verification that doesn't need to place orders, set `DISABLED_STRATEGIES=insider_simple,momentum` so an EDGAR poll mid-test cannot fire a paper order.

- **`get_latest_trade` works with the default feed**, but `get_latest_quote` and `get_bars` should be called with `feed=self.feed` (default `iex`) for free-tier accounts. The broker already does this.
