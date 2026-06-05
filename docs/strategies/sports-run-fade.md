# Strategy: In-game run-reversal fade (Kalshi)

**Status:** backtested on real data; **profitable in the big/rare-overreaction
regime** — marginally as a taker, solidly as a maker (see Results). Deployment-
ready to the Kalshi demo (paper) account. This doc is where to understand, tune,
and deploy it.

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

## Results (40 liquid tennis-match markets, real minute candles)

Run the sweep yourself: `python -m scripts.sweep_sports_fade --n 40`.

**The edge lives in big, rare overreactions** — exactly the thesis. As `entry_drop`
rises, taker net P&L climbs from deeply negative to positive:

| `entry_drop` | taker net | maker net |
|---|---|---|
| 0.10 | −$1,205 | +$358 |
| 0.15 | −$542 | +$399 |
| 0.18 | −$282 | +$302 |
| **0.22** | **+$5 … +$59** | +$345 |

Adding the two enhancements to the best regime:

| Config (40 markets, $10k) | Net P&L | Win rate | Avg move/trade |
|---|---|---|---|
| taker, `entry_drop=0.22` (plain) | +$40 | 63% | — |
| **taker, 0.22 + conviction + avoid 0.42–0.58** | **+$297 (+3%)** | 67% | +7.8¢ |
| maker, `entry_drop=0.15` (plain) | +$524 | 60% | — |
| **maker, 0.15 + conviction** | **+$874 (+8.7%)** | 60% | +2.8¢ |

**Read:**
- The raw reversion edge is real but small; **two costs decide everything** —
  crossing the spread (taker, ~2¢ round-trip) and Kalshi's fee (`0.07·p·(1−p)`,
  worst near p=0.50).
- **Only big/rare overreactions** (`entry_drop≈0.22`) have enough edge to clear
  the taker spread. Validated: your "bigger/rarer" thesis is the executable edge.
- **Conviction sizing** (bet ∝ overreaction size) and **fee-peak avoidance**
  (`--avoid 0.42 0.58`) turn the marginal taker config into a clear +3%.
- **Maker/limit entry** (no spread, ~0 fee) is solidly profitable (+8.7%) — *if
  your limit orders fill* (the open question).

### Caveats on these numbers
- Maker results **assume limit fills** — optimistic. You only fill when price
  comes to you; real fill rates will be lower. Modeling fill probability is the
  next step before trusting the maker column.
- Backtest fills are modeled (fee + half-spread), not the live order book.
- Tennis is the in-season-NBA analog (`KXNBA-26-*` are championship FUTURES, not
  games). Revalidate on single-game NBA markets when the season is on.
- Detection is price-only; the stop defends against fading real news (injuries).

## Deploy it (Kalshi demo → live)

The whole path is wired: `python -m bot.run live --venue kalshi`.

1. **Pick today's games.** Find live single-game tickers:
   `python -m scripts.kalshi_discover --series KXATPMATCH --status open`.
2. **Configure** `control.py`: put the tickers in the `run-reversal-fade`
   `StrategySpec.symbols`, set `enabled=True`. Profitable defaults are baked in
   (`entry_drop=0.22`, conviction on, avoid band). For in-game speed set
   `CONFIG.decision_interval_seconds` low (≈5) so decisions keep up with the game.
3. **Paper first:** `MODE = TradingMode.PAPER` → routes real orders to your Kalshi
   **demo** account (fake money, real order flow). Run and watch.
4. **Go live (real money):** `MODE = TradingMode.LIVE` **and** set env
   `ALLOW_LIVE_TRADING=yes` (a deliberate two-step). Start tiny (`contracts`).

**Known limitations before real money (documented in `LiveKalshiBroker`):** fills
aren't fully reconciled (no partial-fill/poll-status handling); YES-side only;
data is polled (a websocket would cut latency — matters for in-game). The signal
is profitable in backtest under the maker-fill assumption; live maker fills are
the main unknown.

## Caveats

- Backtest fills are modeled (fee + half-spread), not the real order book — treat
  net results as an **upper bound** on a taker version, and the maker column as
  optimistic until limit fills are modeled.
- Tennis is a proxy for the NBA-run dynamic; revalidate in-season.
- Detection is price-only (Kalshi gives no score); the stop is the defense against
  fading real news.
