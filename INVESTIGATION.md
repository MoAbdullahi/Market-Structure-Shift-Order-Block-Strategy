# Why the Strategy Was Not Profitable — Investigation Report

Question investigated: the #1 setup loses money net of costs on all six
instruments (2022-05 → 2026-05). Is it the timeframes (H1/M5)? The stop loss?
The exit structure? The sessions? Something else?

Method: (A) trade-level dissection of the 10,003 trades from the baseline
run (`reports/20260716_201912/`); (B) nine controlled engine variants run on
EURUSD, XAUUSD and NAS100 (one variable changed at a time). "Gross" = before
spread/slippage/commission; "net" = after.

**Caveat:** Phase B comparisons are in-sample diagnostics over the full
4-year window, run to *explain* the loss, not to certify a fix. Any variant
that looks better here still needs out-of-sample (walk-forward) validation
before being believed.

---

## Verdict (ranked)

| Suspect | Verdict |
|---|---|
| **Cost-to-risk mismatch (M5-scale stops vs fixed costs)** | **Guilty — primary cause** |
| **M5 entry timeframe (too fine)** | **Guilty — secondary cause** |
| Target geometry (swept-range target often < 1R away) | Contributing |
| Stop placement (0.1 ATR buffer) | Contributing (too tight *in R terms*, not causing extra stop-outs) |
| Exit structure (Scheme A partials + trailing) | **Not guilty — it adds edge** |
| H1 trigger timeframe | Not guilty (H4 is worse gross) |
| Sessions | Not guilty |
| Direction (long/short) | Not guilty |
| Regime / year | Not guilty |

---

## Phase A — Trade-Level Evidence (pooled, 10,003 trades)

### The signal itself works, everywhere it was measured

| Cut | Gross expectancy |
|---|---|
| Asia (0-7 UTC) | +0.109 R |
| London (7-13) | +0.154 R |
| NY (13-21) | +0.144 R |
| Late (21-24) | +0.091 R |
| Bearish trades | +0.134 R |
| Bullish trades | +0.134 R |
| 2022 / 2023 / 2024 / 2025 / 2026 | +0.17 / +0.09 / +0.10 / +0.17 / +0.15 R |

Positive gross edge in every session, both directions, every year. The
signal logic (CRT sweep → MSS confirm → OB retrace) is not the problem, and
neither are sessions, direction, or regime.

### Costs are the problem

- Cost per trade in R: median **0.17 R**, mean **0.40 R**, 90th pct **0.68 R**.
- R-distance quintiles (pooled): the smallest-R quintile has the **best gross**
  (+0.31 R) and the **worst net** (−0.99 R). Only the largest quintile is net
  ≥ 0 (+0.01 R).
- A straight stop-out costs −1.58 R net instead of −1.0 R.
- Net payoff after costs: avg win +0.67 R vs avg loss −1.43 R → breakeven
  win rate 68 %; achieved 55.5 %. Gross: needs 53.8 %, achieves 61.0 %.

### Target geometry is degenerate in many setups

The target (opposite side of the swept HTF range) is frequently already
consumed by the MSS move before entry:

- **41 %** of trades had a target **< 1 R** away; 21 % < 0.5 R.
- Trades with nominal RR > 5 (tiny stops) lose −0.88 R net despite +0.46 R
  gross — pure cost destruction.

### Setup funnel (context)

45,723 CRT triggers → 17,125 missed (engine busy, single-setup FSM) →
8,456 MSS invalidated → 5,444 discarded (no OB / geometry) → 4,695 pending
expired → **10,003 filled**.

---

## Phase B — Controlled Variants (gross / net expectancy in R)

| Variant | EURUSD | XAUUSD | NAS100 |
|---|---|---|---|
| **Baseline Scheme A (H1/M5)** | +0.143 / −0.469 | +0.117 / −0.177 | +0.145 / −0.008 |
| No partials, static stop, full target | +0.079 / −0.535 | +0.003 / −0.292 | +0.087 / −0.067 |
| Trailing only (no scale-outs) | +0.030 / −0.582 | −0.003 / −0.297 | +0.071 / −0.081 |
| Scale-outs only (no stop moves) | +0.155 / −0.459 | +0.116 / −0.179 | +0.152 / −0.002 |
| Stop buffer 0.5 ATR | +0.134 / −0.317 | +0.131 / −0.036 | +0.114 / **+0.013** |
| Stop buffer 1.0 ATR | +0.091 / −0.271 | +0.068 / −0.055 | +0.070 / −0.020 |
| HTF H4, LTF M5 | +0.059 / −0.233 | +0.054 / −0.053 | +0.047 / −0.019 |
| HTF H1, **LTF M15** | **+0.316** / −0.465 | **+0.313** / **+0.020** | **+0.223** / **+0.013** |
| HTF H4, LTF M15 | +0.189 / −0.124 | +0.176 / **+0.037** | +0.101 / **+0.035** |

Straight-stop rate stayed ~37–42 % across all stop widths — wider stops do
**not** meaningfully reduce stop-outs; they help *only* by making the risk
unit larger relative to costs.

### What the variants prove

1. **Exit Scheme A is exonerated.** Removing partials cuts the gross edge
   roughly in half; trailing-without-scale-outs is the worst variant tested.
   The 50/30/20 scale-out is where most of the gross edge is banked.
2. **The M5 entry timeframe is a real cause.** Identical logic on M15 entries
   doubles-to-triples gross expectancy per trade (fewer, larger-R trades) and
   moves XAUUSD and NAS100 to net-positive. The signal survives coarser
   entry timing; it cannot pay for M5-scale execution.
3. **The H1 trigger timeframe is fine.** H4 triggers weaken gross expectancy;
   H1 is the better bias timeframe of the two tested.
4. **The stop is mis-sized, not mis-placed.** Wider buffers don't avoid
   stop-outs (placement at the swept extreme is sound) but improve net purely
   by enlarging R vs costs — same mechanism as the small-R filter.
5. **FX with these cost assumptions is the worst arena.** EURUSD stays
   negative in every variant; index CFDs and gold, with proportionally
   cheaper costs, are closest to viable.

---

## Bottom line

The strategy's logic produces a genuine, stable, but **thin** gross edge
(~+0.12 to +0.16 R per trade at M5). It is unprofitable because the
structure it trades — M5 Order Blocks with stops just beyond the swept
extreme — creates risk units so small (median trade pays 0.17 R in costs,
often far more) that realistic execution consumes several times the edge.
Secondary: 41 % of setups target a range that is already mostly consumed.

The levers that follow from evidence (all still requiring out-of-sample
validation): trade the same logic at coarser LTF granularity (M15), and/or
enforce a minimum R-to-cost ratio (`risk.min_r_cost_multiple`, currently
under walk-forward test), and prefer low-relative-cost instruments.
