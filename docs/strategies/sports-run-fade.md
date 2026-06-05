# Strategy: In-game run-reversal fade (Kalshi)

**Status:** first signal, backtested on real data. Mechanism validated; **not yet
profitable after costs** at tested parameters (see Results). This doc is the place
to understand and tune it.

## Thesis

During a game, when a team makes a quick run (e.g. 10-0 in Q1), the market
overreacts: the *other* team's win probability drops too far, too fast. Runs are
mostly noise, so the drop tends to **revert**. Trade it: when a single-game win
market's price falls sharply and quickly, **buy it** (fade the drop), then exit
when it reverts part-way back — with a stop if the move was real (injury, real
lead) and a time-stop so we don't ride it to resolution.

## How it's built (where to look / change)

| Piece | File | What to tune |
|---|---|---|
| Signal (state machine) | `bot/framework/signals/sports_fade.py` | `entry_drop`, `reversion_frac`, `stop_drop`, `max_hold`, `lookback`, price band |
| Sizing (discrete trades) | `bot/framework/allocator.py::EventFadeAllocator` | `contracts`, `max_trade_dollars` |
| Cost model | `bot/framework/instruments.py` (`fee_kind="kalshi"`, `slippage_price`) | `half_spread`, `fee_coefficient` |
| Data + backtest | `scripts/backtest_sports_fade.py`, `venues/kalshi/history.py::fetch_game_window` | `--series`, `--n`, `--status` |

**Signal lifecycle** (one instance per market, O(1)/tick):
```
FLAT ──fast drop ≥ entry_drop, price in band──▶ LONG
LONG ──price recovers reversion_frac of the drop──▶ FLAT  (reverted: take profit)
LONG ──price falls another stop_drop below entry──▶ FLAT  (stopped: move was real)
LONG ──held ≥ max_hold bars──────────────────────▶ FLAT  (time stop)
```
`value()` = 1.0 while LONG, 0.0 when FLAT. `EventFadeAllocator` holds a fixed
contract count while LONG (so price drift doesn't churn the position) and exits
on FLAT. Held-to-resolution trades settle at the true outcome via `SimBroker.settle`.

## Run it

```bash
# backtest on liquid settled tennis matches (the in-season NBA analog)
python -m scripts.backtest_sports_fade --n 30 --status settled

# only fade big overreactions, assume maker/limit entry (no spread cross)
python -m scripts.backtest_sports_fade --entry-drop 0.15 --reversion-frac 0.6 --half-spread 0.0

# specific markets / your own series
python -m scripts.backtest_sports_fade --series KXATPMATCH,KXITFMATCH --n 40
```

## Results (30 liquid tennis-match markets, real minute candles)

| Config | Raw edge/trade | Gross P&L | Net P&L (after costs) |
|---|---|---|---|
| `entry_drop=0.08`, taker (1¢ half-spread) | +0.95¢ | −$350 | **−$1,245** |
| `entry_drop=0.15`, taker | +1.90¢ | −$37 | −$433 |
| `entry_drop=0.15`, **maker** (0 spread) | +1.90¢ | **+$237** | −$159 |
| `entry_drop=0.18`, maker, wider target | +1.40¢ | +$102 | −$149 |

**Read:** the thesis is directionally real — reversion happens and the raw edge is
positive (≈+1–2¢/trade, gross turns **positive** once you stop paying the spread).
But the edge is small, and **two costs eat it**:
1. **Spread crossing (taker):** ~2¢ round-trip — bigger than the edge. Going maker
   (limit orders) flips gross positive.
2. **Kalshi fees:** ≈ `0.07·p·(1−p)` per contract per side, *worst near p=0.50* —
   exactly where you fade. Even at zero slippage, fees turned +$237 gross into
   −$159 net.

## What would make it work (ideas to try)

- **Maker/limit entries** to avoid the spread *and* lower fees — the single
  biggest lever. (Needs a limit-order live broker; current `LiveKalshiBroker` is
  market-only.)
- **Bigger, rarer overreactions** (`entry_drop` ≥ 0.15) — fewer trades, bigger
  edge vs the fixed per-trade cost.
- **Avoid p≈0.50** where fees peak; fade moves that land nearer 0.3 or 0.7.
- **Game-state gating:** only fade *run-driven* moves, skip injury/ejection moves
  (real info that won't revert). Needs a live sports-data feed → higher win rate.
- **Validate on real NBA in-season** (single-game markets, not the `KXNBA-26-*`
  championship futures).

## Caveats

- Backtest fills are modeled (fee + half-spread), not the real order book — treat
  net results as an **upper bound** on a taker version, and the maker column as
  optimistic until limit fills are modeled.
- Tennis is a proxy for the NBA-run dynamic; revalidate in-season.
- Detection is price-only (Kalshi gives no score); the stop is the defense against
  fading real news.
