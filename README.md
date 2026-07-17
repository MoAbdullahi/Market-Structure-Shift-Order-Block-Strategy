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

### Follow-up 2: M15 entries, walk-forward validated

The investigation's second lever — running the identical logic on **M15**
LTF bars (`Data/M15/`, `--timeframe M15`) — was tested with the same
walk-forward protocol (12 windows × 6 symbols, small-R filter selected per
train window; results in `reports/opt_walkforward_M15_20260717_010413/`):

| Symbol | OOS expectancy (M15) | Positive windows | (M5 comparison) |
|---|---:|---:|---:|
| US30 | **+0.208 R** | 11/12 | +0.018 |
| XAUUSD | +0.165 R | 9/12 | −0.009 |
| NAS100 | +0.153 R | 9/12 | +0.070 |
| USDJPY | +0.101 R | 10/12 | −0.047 |
| GBPUSD | +0.022 R | 9/12 | −0.062 |
| EURUSD | −0.047 R | 5/12 | −0.045 |

Pooled out-of-sample: **+0.132 R over 2,260 test trades, 53/72 windows
positive** (vs +0.010 R on M5) — positive on 5 of 6 instruments, consistent
across windows, and an order of magnitude above the M5 result. This supports
the diagnosis: the signal's edge is real but cannot pay for M5-scale
execution; at M15 granularity it clears costs on everything except EURUSD.

**Caveat:** the M15 hypothesis was formed after full-sample diagnostics that
overlap these test windows, so this is strong but not pristine evidence —
the definitive confirmation is performance on genuinely new data
(post-2026-05, or instruments outside this basket).

### Follow-up 3: one-shot forward test on genuinely new data

New M15 data (2026-05-12 → 2026-07-17, Dukascopy via `Data/fetch_oos_data.py`;
overlap week verified identical to the research data) was used **once**, with
a configuration frozen beforehand: per symbol, the small-R filter `k` was
selected by training only on the final 12 months of the old data — the exact
procedure the walk-forward validated. Results
(`reports/forward_test_M15_20260717_013643/`):

| Symbol | k | Trades | Win % | Expectancy |
|---|---:|---:|---:|---:|
| XAUUSD | 8 | 49 | 71.4 % | +0.314 R |
| NAS100 | 4 | 42 | 59.5 % | +0.230 R |
| USDJPY | 6 | 2 | 100 % | +0.310 R |
| EURUSD | 4 | 8 | 87.5 % | +0.050 R |
| GBPUSD | 6 | 10 | 80.0 % | +0.040 R |
| US30 | 8 | 29 | 58.6 % | −0.039 R |

**Pooled: +0.181 R over 140 trades (95 % CI +0.003 to +0.359), 67 % win
rate, +25.4 R total.** Positive and consistent with the walk-forward — but
140 trades over ~2 months is well below the sample needed for a confident
verdict (the CI barely excludes zero), and US30, the best walk-forward
instrument, was slightly negative this period — instrument-level results at
this sample size are noise. Verdict: **survives so far**; keep extending the
forward window before sizing up.

### Follow-up 4: independent data-source replication (histdata.com)

All key results were re-run on an independent feed: histdata.com free M1
bars resampled to M15 (`Data/fetch_alt_data.py` → `Data/ALT/M15/`).
histdata covers 5 of the 6 instruments (no Dow product exists there, so
US30 has no alternate source; the Kaggle NASDAQ-100 dataset turned out to
be *daily bars of individual member stocks* — unusable for intraday
testing). Data note: histdata's docs claim fixed EST timestamps, but
alignment against Dukascopy proves they are US Eastern **with DST**; after
correction the feeds match bar-for-bar (return correlation 0.86–0.94).

Replication on the alternate feed (`reports/altsource_replication_*`,
`reports/opt_walkforward_ALT_M15_*`):

- **Full-period M15 baseline:** same sign and ordering on all 5 symbols
  (e.g. EURUSD −0.471 R vs −0.491 R on Dukascopy; XAUUSD +0.044 vs +0.020).
- **Walk-forward, same 5-symbol basket:** pooled OOS **+0.104 R
  (1,684 trades, 40/60 windows positive)** vs **+0.111 R (1,768 trades,
  42/60)** on Dukascopy; per-symbol signs identical (EURUSD negative on
  both, NAS100 +0.157 vs +0.153).
- **Forward window** (2026-05-12 → 06-26, frozen k): pooled +0.167 R over
  81 trades vs +0.181 R on Dukascopy.

The results are properties of the market, not artifacts of one data vendor.

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
