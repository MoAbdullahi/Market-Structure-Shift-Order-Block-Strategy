# USDJPY Trading Journal — TradingView Bar-Replay Study (2022 → 2026)

Manual multi-timeframe replay of the CRT + MSS + Order Block method on TradingView,
cross-checked against the engine's backtest log (`reports/20260717_010220/USDJPY_trades.csv`,
967 trades, 2022-05 → 2026-05).

**Method under test (as replayed on the chart):**

- **1H (HTF)** — CRT sweep: current 1H candle takes out the prior 1H high and closes back
  below it (bearish; mirror for bullish). Prior 1H range must be meaningful (≥ 0.5 × ATR(14) 1H).
- **15M (LTF)** — after the 1H trigger closes: mark the reference low/high from the first
  3 LTF candles, wait for a close beyond it = **MSS**.
- **Order Block** — last opposite-colored LTF candle before the MSS break; its body is the
  limit-entry zone.
- **Stop** — beyond the swept 1H extreme + 0.1 × ATR(14) LTF buffer.
  **Target** — opposite side of the swept 1H range.
- **Management (Scheme A)** — 50% off at 1R (stop → breakeven), 30% at 2R (stop → +1R),
  20% runs to the HTF target.
- **Filter learned from backtesting** — skip setups where the risk distance is small
  relative to trading costs (small-R filter, k≈6 for USDJPY): tiny-R setups are the
  single biggest documented loss driver.

Timeframe labels used in all chart drawings: **1H** for HTF structure, **15M** for entries.

---

## Replay platform

TradingView **desktop app** driven via its debugging interface (`tools/tv_driver.py`),
signed in as HashimAbdullahi. OANDA:USDJPY feed, chart timezone UTC, Bar Replay from
2022-01-03. Trades are placed as real **Replay Trading** paper orders (limit + attached
TP/SL) so TradingView draws the levels and keeps its own trade list, then replay is
stepped bar by bar to watch each trade resolve. Feed note: OANDA prices differ from the
engine's Dukascopy/histdata feeds by a few pips — fills can occur hours apart on the
same setup; structure and outcomes have matched so far.

## Session log

| # | Date (UTC) | Dir | Entry | Stop | Target | RR to tgt | Result | Taken/Missed/Skipped | Notes |
|---|-----------|-----|-------|------|--------|-----------|--------|----------------------|-------|
| 1 | 2022-01-04 19:00 | Long | 116.114 | 115.948 | 116.258 | 0.87 | **−1R** (stop) | Taken | 1H CRT sweep of 116.037 low → 15M OB 116.114; TV trade list: −1,020 JPY on 10K (early accidental flat at 116.012; rule-based exit −1,660 JPY at stop — bar low 115.907 breached 115.948) |
| 2 | 2022-01-27 ~06:30 | Long | 114.627 | 114.468 | 114.690 | 0.40 | **WIN** (target, +630 JPY on 10K; engine +0.23R) | Taken | London-open bullish CRT; limit rested below price, filled and TP hit inside the 06:00–07:00 hour (TV: exit 07:00 @114.690, SL auto-cancelled by OCO). Fast fill→resolve; textbook session behavior. Under the rejected "RR≥1" draft rule this winner would have been missed — more evidence that rejection was right. |
| 3 | 2022-03-29 00:00 | Short | 123.760 | 123.948 | 123.560 | 1.06 | **−1R on OANDA** (stop 123.948, −1,880 JPY on 10K); engine feed: **+0.89R win** | Taken | Tokyo-open bearish CRT after the March JPY-collapse rally. Entry and stop-out inside the same 00:00 hour: the OANDA retrace ran through 123.948 before dropping ~120 pips — the drop the engine's feed captured as a clean win. Root cause below. |

| 4 | 2022-05-05 10:15 | Short | 129.652 | 129.836 | 129.462 | 1.03 | **−1R** (stop 11:15; engine −1.10R — both feeds agree) | Taken | Day after FOMC (May 4 50bp hike). Setup annotated live on chart: "1H CRT SWEEP of prior 1H high (~129.83)" + "15M MSS breakdown → OB retest". Screenshot: `reports/replay_screens/trade4_2022-05-05_setup_labeled.jpg`. Post-mortem below. |
| 5 | 2026-04-20 10:45 | Short | 158.913 | 159.081 | 158.725 | ~1.0 | **WIN** (+0.90R engine; data-verified: TP touched 13:15, SL never touched — post-entry high 158.972) | Taken | NY-overlap short from the 2026 regime (best year: +0.24R mean on 28 filtered trades). TV paper record polluted by the instant-fill artifact (entry and bar-close exit −170 JPY) — see replay-mechanics notes; market outcome verified directly against M15 data. |

### Trade 4 — losing short against a post-FOMC V-recovery

The mechanical setup was clean: sweep, 15M MSS down, OB retest filled at 10:15 London.
It lost because the *context* was a V-shaped recovery of the prior day's FOMC plunge —
momentum was strongly up, and the swept "prior 1H high" had been formed inside the
FOMC whipsaw itself, making it a meaningless liquidity reference. Price stopped the
trade at 11:15 and kept running 16 more pips without pausing.

**Lessons (chart-derived heuristics, graded on future replays — not yet testable
offline):** (a) skip CRT signals whose swept level was created inside a major news
candle (FOMC/CPI/NFP); (b) treat a sweep against a same-day V-recovery as trend
continuation fuel, not reversal liquidity.

### Trade 3 — the feed-fragility discovery (most important finding of the replay study)

The engine (histdata feed) and the replay (OANDA feed) disagree **on the same setup**:
engine +0.89R win, OANDA −1R loss. Why: the 23:00–00:00 OANDA candle spiked to
**124.152**, but the ALT-feed trigger candle high was ~**123.90** (stop = trigger high
+ 0.1×ATR = 123.948). Same strategy, same clock hour — different candle shapes, because
Tokyo-open liquidity is thin and hour boundaries/liquidity providers differ between
feeds. A stop that cleared the sweep by a buffer on one feed sat *inside* the retrace
on the other.

**Adopted rule (replay-derived, consistent with session stats):** treat 23:00–03:00 UTC
(Tokyo open) setups as non-tradeable or half-risk — not because the average edge is
negative (Asia pool: +0.055R) but because the *levels themselves* are not robust across
data sources; a live broker feed can invalidate the backtested geometry. London/NY
setups (trades 1–2) replicated almost exactly across feeds. Robustness is part of edge.

---

## Losing trades — why each one lost

### Trade 1 — 2022-01-04 long (−1R)

**Setup (as seen on the replayed chart):** Jan 3–4 was a violent one-day rally
(~115.2 → 116.35). The 16:00 1H candle swept the prior 1H low (116.037, prior range
116.258–116.037, 22 pips ≥ 0.5×ATR) down to ~115.95 and closed back inside → bullish
CRT trigger. MSS confirmed on 15M; last opposite-colored 15M candle gave the OB at
116.114. Limit filled 19:00 UTC.

**Why it lost — three compounding causes, all visible in replay:**
1. **Degenerate geometry.** Target (opposite side of swept range, 116.258) was only
   0.87× the risk distance. The engine flagged exactly this class as the loss driver
   (41% of setups target <1R). It passed the k=6 cost filter — barely.
2. **Dead-session entry.** Fill came 19:00–01:00 UTC (post-NY, pre-Tokyo). Five 1H
   candles chopped sideways on no volume, then broke down at Asia open. The sweep's
   energy had dissipated hours before the retracement reached the OB.
3. **Momentum context.** The three 1H candles before entry were all red after a
   blow-off top at 116.35 — the "sweep" was better read as the *start* of a deeper
   pullback, not a spring. A crisp rejection candle (long wick, close in upper third)
   was absent; the trigger closed mid-range.

**Lessons drafted after this trade — then TESTED against the 391-trade filtered
playbook before adoption (a rule only survives if the data supports it):**

| Draft rule from trade 1 | Test result on k6 pool | Verdict |
|---|---|---|
| Demand target RR ≥ 1 | RR≥1 subset: −0.055R mean (94 trades) vs +0.099R full pool — the sub-1R-target trades are high-win-rate scalps that *carry* the edge (WR ~75%) | **REJECTED** |
| Avoid dead-session entries (17–23 UTC) | 17–23 UTC: −0.000R (90 trades) vs London 06–10: +0.123R, NY 11–16: +0.197R, Asia: +0.055R | **ADOPTED** — prefer 06–16 UTC; treat 17–23 UTC as lowest quality |
| Trigger candle must close in upper/lower third | not yet testable offline (needs per-trigger candle data) | Graded visually on each replayed trade |

This is the core discipline of the study: a lesson from one chart is a hypothesis,
not a rule, until the playbook data confirms it.

**Process note (replay mechanics):** the platform exit shows −1,020 JPY because a UI
click accidentally closed the position at 116.012 before the stop; the stop would have
exited at 115.948 (−1,660 JPY). Fix: never click near the chart's position widget;
dismissable notifications are left to fade on their own.

---

## Missed trades

Quantified against the full 2022–2026 playbook (1,061 setups on this data):

- **Skipped by the small-R filter (k=6): 670 setups, mean −0.388R.** These are the
  correct misses — the filter's whole value. Not one of them is regretted.
- **Would-have-missed under the rejected "RR≥1" draft rule: 297 of the 391 filtered
  trades** — including journal trade 2 (a winner). The RR<1 subset carries the pool's
  edge (high win-rate scalps to the near side of the swept range). Biggest lesson in
  the "missed trades" category: *a plausible-sounding discretionary filter is itself
  the main source of missed trades.* Every proposed skip-rule must be tested on the
  playbook before adoption.
- **Replay-identification misses:** in the five live-replayed setups, the mechanical
  levels were computed from the playbook before stepping, so no setup was missed in
  real time. Without the playbook, trade 3 (Tokyo, 00:00) would likely have been
  missed by a human — the trigger, MSS, retest and stop-out all completed inside two
  1H bars while the sweep shape differed per feed.

---

## Zones that trade best (final list, tested on 391 filtered trades 2022–2026)

| Zone | n | Mean R | WR | Verdict |
|---|---|---|---|---|
| **NY overlap, 11:00–16:00 UTC** | 112 | **+0.197** | 77% | Best zone. Retracements fill and resolve within 1–3 bars (trades 2, 5). |
| **London open, 06:00–10:00 UTC** | 91 | +0.123 | 74% | Second best; same fast-resolve behavior. |
| Asia, 00:00–05:00 UTC | 98 | +0.055 | 72% | Positive on average but **feed-fragile** (trade 3): thin liquidity means trigger candles differ across data sources — backtested levels may not exist on a live broker feed. Half-risk or skip. |
| Post-NY, 17:00–23:00 UTC | 90 | −0.000 | 67% | Dead zone (trade 1). Retracements drift for hours and break down at Asia open. Skip. |

By year (filtered pool, n / mean R): 2022 94 / +0.09 · 2023 67 / +0.09 ·
2024 85 / +0.12 · 2025 117 / +0.06 · 2026 28 / **+0.24**. Positive every year;
2026 is the strongest regime so far.

Price-structure zones (chart-derived): OBs that form ≥2 candles *before* the MSS break
and sit in the upper half of the swept range (bearish; mirror for bullish) resolved
fastest in replay. Levels formed inside major-news candles (FOMC/CPI) are unreliable
sweep references (trade 4).

---

## Method improvements adopted mid-study

Each numbered change was adopted *during* the study, in order, and every data-testable
rule was validated on the playbook before adoption:

1. **After trade 1 (dead-session loss):** drafted three rules; tested all three.
   Adopted the session rule (prefer 06:00–16:00 UTC, avoid 17:00–23:00), **rejected**
   the RR≥1 rule (it deletes the edge), kept the trigger-candle-close check as a
   visual grading criterion.
2. **After trade 3 (feed divergence):** adopted the robustness rule — Tokyo-open
   (23:00–03:00 UTC) setups at half-risk or skipped, because their levels are not
   reproducible across feeds. A live edge must survive a change of data vendor.
3. **After trade 4 (post-FOMC loss):** adopted the news-level heuristic — skip sweeps
   of levels created inside major-news candles; do not fade same-day V-recoveries.
4. **Process rules (replay mechanics):** only rest limit orders (never place when
   price is at/through the level — instant fills lose their brackets in the
   simulator); never click near the chart position widget; verify every ambiguous
   platform exit against raw M15 data before journaling it as a strategy result.

**Net effect of 1–3 on the filtered pool (approximate, applying session rule only):**
06:00–16:00 subset = 203 trades, +0.164R mean vs +0.099R for all sessions — roughly a
two-thirds improvement in per-trade expectancy while keeping >half the trade count.

---

## Replay-vs-engine agreement summary

| Trade | Engine (its feed) | Replay (OANDA) | Agree? |
|---|---|---|---|
| 1 (Jan 04) | −1.16R stop | stop breached (bar low 115.907 < 115.948) | ✔ loss both |
| 2 (Jan 27) | +0.23R target | TP hit 07:00 | ✔ win both |
| 3 (Mar 29) | +0.89R target | −1R stop — **feeds disagree** (Tokyo) | ✘ |
| 4 (May 05) | −1.10R stop | stop 11:15 | ✔ loss both |
| 5 (2026-04-20) | +0.90R target | TP touch 13:15 verified in data | ✔ win both |

4/5 agree; the one disagreement is precisely the Tokyo-session fragility documented
above. London/NY setups replicated across feeds in every case examined.

---

## Prior knowledge carried into this study (from the backtest, so the replay doesn't start blind)

1. **Small-R setups lose.** Median cost ≈ 0.17R per trade; 41% of raw setups target < 1R.
   On the chart this means: if the swept 1H range is narrow and the OB sits close to the
   sweep extreme, the trade is not worth taking even when it "works".
2. **USDJPY was one of the better symbols** in walk-forward (+0.10 to +0.13R OOS with the
   filter), so valid setups deserve to be taken — the edge is real but thin.
3. **All sessions trade**, but cost-adjusted results were driven by setups with wide 1H
   ranges — these cluster around London and NY opens on USDJPY.
4. **Exit Scheme A is not the problem** — removing partials halved the gross edge in
   testing. Keep the 50/30/20 management during replay.
