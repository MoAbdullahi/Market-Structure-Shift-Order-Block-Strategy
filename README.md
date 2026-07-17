# CRT + Market Structure Shift + Order Block Strategy

A modular Python backtesting engine implementing the Candle Range Theory (CRT)
liquidity-reversal strategy with a two-timeframe hierarchy, built to the
specification in `Implementation Task Report.txt`.

---

## How the Strategy Works

The strategy combines higher-timeframe liquidity sweeps with lower-timeframe
confirmation before entering on a retracement into an Order Block.

**Timeframes:** HTF = 1 Hour (bias + trigger), LTF = 5 Minutes (confirmation + entry).

### 1. HTF CRT Trigger (H1)
Every completed H1 candle is checked against the previous completed H1 candle:

- **Bearish CRT** — the candle's high sweeps above the previous high and it
  closes back below that high (a liquidity grab that reverses).
- **Bullish CRT** — the mirror: sweep below the previous low, close back above it.
- **Range filter** — the previous candle's range must be ≥ `0.5 × ATR(14)` on
  the H1, so trivially small ranges don't count as valid liquidity.

### 2. LTF MSS Confirmation (M5)
After the trigger, the engine scans forward on M5:

- A **reference level** is built from the first `reference_candle_count`
  (default 3) completed M5 candles after the H1 close — the reference low for
  bearish setups, reference high for bullish.
- **MSS confirms** when a later M5 candle *closes* beyond that reference,
  proving the HTF reversal is playing out on the lower timeframe.
- No trade is permitted before MSS confirmation. If it doesn't confirm within
  `mss_lookback` candles the setup is invalidated.

### 3. Order Block + Pending Entry
- The **Order Block** is the last opposite-colored M5 candle before the MSS
  break (bearish setup → last bullish candle; bullish → last bearish). Its
  *body* defines the level; the entry price mode is configurable
  (midpoint / open / close / body high / body low).
- A **pending limit order** is placed at that level — the position opens only
  if price retraces back into the OB. No market entries. The order expires
  after `pending_lifetime` (default 24) M5 candles.

### 4. Risk & Exits (Scheme A)
- **Stop:** swept extreme (HTF trigger high/low) ± `0.1 × ATR(14)` buffer on the LTF.
- **Target:** the opposite side of the swept HTF range (full reversion).
- **Partials:** 50 % closes at 1R, 30 % at 2R, the final 20 % rides to the target.
- **Stop management:** after the first partial the stop moves to breakeven;
  after the second it trails to the 1R level.

The default configuration reproduces the **#1 setup**: OB entries only,
Confirm(MSS) required, All Sessions, Strong Filter OFF, Premium/Discount
Filter OFF.

---

## Engine Design

| Module | Responsibility |
|---|---|
| `engine/indicators.py` | Wilder ATR (causal) |
| `engine/crt.py` | HTF CRT detection (+ optional Strong Filter) |
| `engine/mss.py` | MSS reference + confirmation tracking |
| `engine/orderblock.py` | OB identification, 5 pricing modes |
| `engine/entries.py` | Pending limit orders with lifetime expiry |
| `engine/risk.py` | Stop/target/R geometry + validation |
| `engine/execution.py` | Spread / commission / slippage cost model |
| `engine/states.py` | Finite state machine (Idle → AwaitingMSS → AwaitingRetracement → ActiveTrade → Closed) |
| `engine/trade.py` | Scheme A partials + dynamic stop movement |
| `engine/analytics.py` | Trade / equity / risk / execution metrics |
| `engine/backtester.py` | Event-driven, bias-free simulation loop |
| `engine/strategy.py` | Orchestration of the full pipeline |
| `main.py` | Configuration + execution entry point |
| `optimize.py` | Grid / random search, walk-forward, Monte Carlo |

**Bias controls built in:**

- **Time synchronization** — the CRT signal is generated only when the H1
  candle has *closed*; M5 scanning starts with the first completed M5 candle
  after the H1 close. (Verified by an end-to-end synthetic test.)
- **Deterministic FSM** — illegal state transitions raise immediately.
- **Conservative intrabar rules** — when one candle touches both the stop and
  a profit level, the stop is assumed hit first (`stop_first`); stop moves
  from partials apply from the next candle; gaps through levels fill at the open.
- **Costs from trade one** — every fill is adjusted adversely by half-spread
  + slippage; commission charged per side. All per-instrument and configurable.

Every parameter is externalized in `config/config.yaml`.

---

## What Is Tested and How

### 1. Unit / integration tests (`tests/`, 45 tests)
- ATR causality and Wilder recursion.
- CRT detection: both directions, range filter boundary, ambiguous double
  sweep, strong filter, NaN ATR.
- MSS: reference building, close-beyond confirmation, lookback invalidation,
  no confirmation during the reference window.
- Order Block: last-opposite-candle selection, doji handling, all 5 pricing modes.
- Pending orders: limit fills, gap fills at open, lifetime expiry.
- Trade management: full Scheme A sequence, breakeven and 1R trail, stop-first
  priority, next-candle stop application, gap-through-stop, cost accounting
  (incl. entry-side commission), forced end-of-data close.
- Backtester: an engineered synthetic dataset proving the signal only fires
  after H1 close and entry/exit land on the exact expected M5 candles, plus a
  random-walk run asserting accounting invariants (equity reconciles with the
  sum of trade PnLs, every trade fully exited).

Run: `python -m pytest tests/`

### 2. Historical backtest
- **Data:** M5 OHLCV, 2022-05-12 → 2026-05-12 (~4 years, UTC), six
  instruments: EURUSD, GBPUSD, USDJPY, XAUUSD, NAS100, US30 (`Data/*.parquet`).
- **Setup:** default config (#1 setup), 100 000 starting equity, 1 % of
  current equity risked per trade, per-instrument spread/slippage/commission.
- Run: `python main.py` → per-symbol metrics JSON, trades CSV, equity CSV and
  a combined summary under `reports/<timestamp>/`.

### 3. Optimization framework
- `python optimize.py --mode grid|random` — search any dotted config key over
  the space in `config.yaml → optimization.space`.
- `python optimize.py --mode walkforward` — rolling train/test windows; best
  train-window parameters evaluated on the following unseen test window.
- `python optimize.py --mode montecarlo` — bootstrap of the realized R-series
  (10 000 paths) for outcome and drawdown distributions.

---

## Results (full 4-year window, #1 setup, net of costs)

| Symbol | Trades | Win % | Expectancy (R) | Profit Factor | Sharpe |
|---|---:|---:|---:|---:|---:|
| EURUSD | 1778 | 49.7 % | −0.469 | 0.52 | −4.60 |
| GBPUSD | 1790 | 50.5 % | −0.458 | 0.50 | −4.21 |
| USDJPY | 1782 | 56.0 % | −0.296 | 0.54 | −3.06 |
| XAUUSD | 1765 | 59.2 % | −0.177 | 0.69 | −2.06 |
| NAS100 | 1469 | 60.6 % | −0.008 | 0.95 | −0.10 |
| US30   | 1419 | 58.5 % | −0.088 | 0.81 | −1.02 |

**Net of realistic execution costs, the strategy loses on all six instruments
over this period.** With 1 % compounding risk per trade the FX equity curves
are effectively wiped out; NAS100 is the closest to breakeven.

### Cost attribution (the key finding)

The same runs with **zero costs** are positive everywhere:

| Symbol | Gross Win % | Gross Expectancy (R) |
|---|---:|---:|
| EURUSD | 61.7 % | +0.143 |
| GBPUSD | 59.8 % | +0.115 |
| USDJPY | 62.6 % | +0.163 |
| XAUUSD | 60.9 % | +0.117 |
| NAS100 | 61.3 % | +0.145 |
| US30   | 58.9 % | +0.118 |

The raw signal logic has a consistent positive gross edge (+0.12 to +0.16 R,
~60 % win rate) across all six instruments — but the edge per trade is small
in *price* terms. Average stop distance is only ~9 pips on EURUSD (~2 hours
average holding time), so a ~2-pip round-trip cost consumes ~0.25 R on a
typical trade and far more on the tightest setups; trade-level analysis shows
many small-R setups where costs exceed even a +1R gross outcome. Monte Carlo
on NAS100 (the best net instrument): median outcome −11 R, P(loss) ≈ 58 %,
p99 drawdown ≈ 162 R.

**Conclusion:** as specified, the #1 setup does not survive realistic
execution costs on M5 entries. The gross edge is real but too thin for its
trade frequency and stop size. The obvious levers to explore with
`optimize.py` (walk-forward, so any improvement is validated out-of-sample):
filtering out small-R setups, lower-cost execution assumptions, session
filters, or coarser entry timing.

*(All numbers reproducible: `reports/` contains the full metrics JSON, trade
lists, and equity curves for the run shown above.)*

### Follow-up: root-cause investigation and small-R filter (walk-forward)

`INVESTIGATION.md` documents a full diagnosis of the loss. Summary: the
signal has a stable gross edge in every session, direction, and year; the
loss is caused by execution costs overwhelming tiny M5-scale risk units
(median cost 0.17 R/trade), compounded by 41 % of setups targeting a range
already mostly consumed. The exit scheme and the H1 trigger are *not* the
problem; M5 entry granularity partly is.

A small-R filter (`risk.min_r_cost_multiple`: reject setups whose R distance
is under k × round-trip cost) was added and validated by walk-forward
(12-month train → 3-month unseen test, rolling, 12 windows × 6 symbols,
k ∈ {0,2,4,6,8}; results in `reports/opt_walkforward_20260717_001931/`):

- Pooled out-of-sample expectancy improves from **−0.24 R to +0.01 R**
  (3,315 test trades) — the filter removes most of the cost damage but the
  result is **breakeven, not a validated edge** (35/72 windows positive;
  not statistically distinguishable from zero).
- Only NAS100 (+0.07 R, 8/12 windows positive) and US30 (+0.01 R) are OOS
  positive; FX pairs remain negative. Treating the index results as an edge
  would be post-hoc instrument selection — it is a hypothesis for new data,
  not a conclusion.

---

## Usage

```bash
# full backtest, all instruments
python main.py

# subset / window
python main.py --symbols EURUSD XAUUSD --start 2023-01-01 --end 2024-01-01

# tests
python -m pytest tests/

# optimization
python optimize.py --mode grid --symbols EURUSD
python optimize.py --mode walkforward
python optimize.py --mode montecarlo
```

Requires Python 3.10+ with `pandas`, `numpy`, `pyarrow`, `pyyaml`, `pytest`.
