# Framework design notes

The multi-asset, event-driven signal framework lives in `bot/framework/`. This
is the new core; the thread/queue prototype in `bot/core` (+ `bot/main`,
`bot/sources`, `bot/strategies/regular`) is now superseded and can be deleted
once you're happy here — it's preserved for now so nothing breaks mid-migration.
The two practice strategies (`insider_simple`, `momentum`) were **not** ported:
they're discrete filing-triggered logic, a different shape from the continuous
market-state signals this framework is built for. They remain in git history to
resurrect later as proper signals if wanted.

## Why these structural calls

- **asyncio, not threads.** One consumer, `asyncio.Queue`, sources as tasks.
  Scales to many instruments cleanly and is the natural fit for websocket feeds
  (crypto via ccxt.pro, Alpaca stream) when we wire them.
- **One package, mode-agnostic.** `live.py` and `backtest.py` build the *identical*
  engine/signals/allocator/risk/broker through `assembly.build_engine`. The only
  difference is the `Source` list (live adapter + ClockSource vs ReplaySource).
- **`InstrumentSpec` + `MarketAdapter` for the asset-class seam.** Static
  description (tick/lot/fees/constraints/lifecycle) on the spec; dynamic behavior
  (feed, calendar, roll) on the adapter. The core never branches on asset class —
  it reads declarations off the spec. Adding FX/options later = one adapter + specs.
- **Decisions on the Clock only.** Every market event updates state in O(1); the
  expensive allocator step runs only on `Clock` events, conflating bursts to the
  latest state. Live: a wall-clock `ClockSource`. Backtest: the `ReplaySource`
  interleaves Clocks on the data's timeline, so backtests are deterministic and
  don't sleep.
- **Normalization is structural.** Signals emit z-scores; the reference allocator
  only *ranks* them (long top slice / short bottom slice, equal weight, vol-unit).
  A flat "X% move" threshold has nowhere to live — by design.
- **Resolution/settlement is a first-class event**, not an edge case. It's the
  path prediction-market contracts and futures use to terminate at a fixed value;
  `SimBroker.settle` pays out and the `Universe` drops the instrument.

## Components

| Concern | Module |
|---|---|
| Normalized events (Trade/Quote/Bar/Resolution/Clock) | `events.py` |
| Asset-class abstraction | `instruments.py` (spec), `adapters/` |
| Maintained state + incremental stats (O(1)) | `state.py` |
| Signals (plug-in: subclass + `@register`) | `signals/`, `registry.py` |
| Universe + churn | `universe.py` |
| Portfolio construction | `allocator.py` |
| Book-level risk + kill switch | `risk.py` |
| Broker iface + SimBroker (fills/fees/PnL/settlement) | `broker.py` |
| Recorder (equity curve, fills) | `recorder.py` |
| Async engine | `engine.py` |
| Sources (clock, base) | `sources.py` |
| Backtest replay + synthetic data | `replay.py` |
| Wiring | `assembly.py`, `config.py` |
| Entrypoints | `bot/live.py`, `bot/backtest.py` |
| Analysis (PnL/Sharpe/maxDD/turnover) | `scripts/analyze.py` |

## Asset classes

- **Equities (Alpaca)** — fully wired in `adapters/equities_alpaca.py`. Uses
  Alpaca's **websocket stream** (trades + quotes) on our asyncio loop, with a
  REST-polling fallback if the socket can't connect. Shortability is read live
  from the asset's `shortable` flag; session state from the Alpaca clock.
  Verified end-to-end against the live IEX feed. Execution is always `SimBroker`
  — no real orders. (Latency floor is the feed: IEX is ~15 min delayed; SIP for
  real-time.)
- **Prediction markets** — `adapters/prediction_market.py` is a deliberate **stub**
  that replays a scripted lifecycle (quotes → resolution) to prove the seam:
  probability prices in [0,1], long-only/capped constraints, and the settlement
  path all flow through the unchanged core. Wire Kalshi/Polymarket here next.
- **Crypto / futures** — not yet present; each is one new adapter emitting specs +
  events, no core changes.

## Control panel & launcher

`control.py` (project root) is the one file you edit: the global `ENABLED` switch,
`MODE` (SIM / PAPER / LIVE), book-level `CONFIG`, the `STRATEGIES` list (each with
an `enabled` toggle, signal, params, universe, capital slice), and the backtest
window. `bot/run.py` reads it and dispatches.

- **Modes** (`modes.py`): `SIM` = SimBroker (fake fills, default), `PAPER` = real
  orders to the Alpaca paper account, `LIVE` = real money. Credentials resolve per
  mode from env (`ALPACA_PAPER_*` / `ALPACA_LIVE_*`, legacy `ALPACA_*` = paper).
  LIVE refuses to arm unless `ALLOW_LIVE_TRADING=yes` — a deliberate second step.
- **Multi-strategy:** the engine runs all enabled strategies concurrently against
  one shared book; each proposes targets over its own universe/capital slice and
  the engine sums them, then the RiskMonitor gates the total once.
- **History** (`history.py`): `fetch_or_load` pulls real Alpaca bars and caches
  them to `data/` as CSV, so backtests run on real prices (not just synthetic).

```bash
source .venv/bin/activate
python -m bot.run backtest --synthetic                  # random-walk, no creds
python -m bot.run backtest                              # real bars per control.BACKTEST
python -m bot.run backtest --start 2023-01-01 --end 2023-06-30 --timeframe 1Day
python -m bot.run live                                  # live data; SimBroker/paper/live per MODE
python -m pytest tests/                                 # 17 tests
```

## Known rough edges / next steps

- Reference signal is intentionally noise-churning (it tripped the kill switch on
  the synthetic demo). Real signals come later; this only validates plumbing.
- IEX feed is ~15 min delayed — the data floor, independent of our transport.
  Move to SIP (`ALPACA_DATA_FEED=sip`) for real-time when it matters.
- Crypto and prediction-market adapters are next (crypto via ccxt; replace the
  prediction-market stub with Kalshi/Polymarket).
- The `ui/` backtest service is still the old, separate one — eventually retire it
  in favor of `bot/backtest.py` so there's a single backtest path.
