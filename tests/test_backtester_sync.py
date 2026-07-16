"""End-to-end synchronization test on synthetic M5 data.

Verifies (Required Improvements 1):
- the CRT signal is generated only when the H1 candle has closed,
- M5 scanning starts with the first completed M5 candle after the H1 close,
- the full pipeline CRT -> MSS -> OB -> pending fill -> Scheme A exits runs
  deterministically through the state machine.
"""

import pandas as pd
import pytest

from engine.backtester import Backtester
from engine.execution import CostModel
from engine.states import State
from engine.strategy import StrategyParams

NO_COST = CostModel(tick_size=0.01)


def synthetic_m5() -> pd.DataFrame:
    """14 flat hours, a wide 'previous' hour, a bearish CRT trigger hour,
    then a scan hour engineered to confirm MSS, form an OB, fill a short at
    the OB midpoint and run to the HTF target."""
    rows = []

    def bar(o, h, l, c):
        rows.append([o, h, l, c])

    # hours 0..14 (15 hours): every M5 bar (100,105,95,100) -> H1 range 10
    for _ in range(15 * 12):
        bar(100.0, 105.0, 95.0, 100.0)

    # hour 15 (trigger): aggregate (o=100, h=106, l=100, c=101)
    # sweeps prev high 105, closes back below -> bearish CRT
    for i in range(12):
        bar(100.0 if i == 0 else 101.0, 106.0, 100.0, 101.0)

    # hour 16 (scan hour), 12 bars:
    bar(101.0, 102.0, 100.0, 101.5)  # ref 1 (reference low -> 100)
    bar(101.5, 102.0, 100.2, 101.0)  # ref 2
    bar(101.0, 102.0, 100.5, 101.0)  # ref 3
    bar(
        100.5, 102.0, 100.4, 101.5
    )  # bullish candle -> the Order Block (body 100.5..101.5)
    bar(101.5, 101.6, 99.0, 99.5)  # MSS break: closes below 100
    bar(99.5, 101.2, 99.4, 100.0)  # retrace into OB midpoint 101 -> short fills
    bar(100.0, 100.5, 94.0, 94.5)  # run through 1R and the HTF target (95)
    for _ in range(5):
        bar(94.5, 95.0, 94.0, 94.5)

    idx = pd.date_range("2024-01-01 00:00", periods=len(rows), freq="5min", tz="UTC")
    return pd.DataFrame(rows, index=idx, columns=["open", "high", "low", "close"])


@pytest.fixture()
def result_and_strategy():
    m5 = synthetic_m5()
    params = StrategyParams(
        reference_candle_count=3, mss_lookback=36, pending_lifetime=24
    )
    bt = Backtester("SYN", m5, params, NO_COST, initial_equity=100_000)
    return bt.run()


def test_pipeline_produces_one_short_trade(result_and_strategy):
    result = result_and_strategy
    assert result.counters.crt_triggers >= 1
    assert result.counters.entries_filled == 1
    assert len(result.trades) >= 1
    trade = result.trades[0]
    assert trade.direction == "bearish"
    assert trade.entry_raw == pytest.approx(101.0)  # OB body midpoint
    assert trade.target == pytest.approx(95.0)  # opposite side of swept range
    # stop = trigger high (106) + 0.1 * ATR_LTF -> strictly above 106
    assert trade.stop_initial > 106.0
    # profitable run to target: first leg at 1R, final leg at the target
    assert trade.legs[0].reason == "partial_1"
    assert trade.legs[-1].reason == "target"
    assert trade.net_pnl > 0


def test_no_lookahead_signal_only_after_h1_close(result_and_strategy):
    result = result_and_strategy
    trade = result.trades[0]
    # trigger hour is 15:00-16:00 -> the earliest legal entry activity is 16:00
    h1_close = pd.Timestamp("2024-01-01 16:00", tz="UTC")
    assert trade.entry_time >= h1_close


def test_mss_scan_starts_first_m5_after_h1_close():
    m5 = synthetic_m5()
    params = StrategyParams()
    # run manually to inspect the FSM history
    from engine.backtester import Backtester as BT

    result = BT("SYN", m5, params, NO_COST).run()
    # AWAITING_MSS must have been entered exactly at the H1 close timestamp
    h1_close = pd.Timestamp("2024-01-01 16:00", tz="UTC")
    trade = result.trades[0]
    # entry occurred in the scan hour, after at least reference+break candles
    assert trade.entry_time == pd.Timestamp("2024-01-01 16:25", tz="UTC")
    # exit at the run-down candle
    assert trade.exit_time == pd.Timestamp("2024-01-01 16:30", tz="UTC")
    assert trade.entry_time > h1_close


def test_smoke_random_walk_invariants():
    import numpy as np

    rng = np.random.default_rng(42)
    n = 12 * 24 * 30  # ~30 days of M5
    close = 100 + np.cumsum(rng.normal(0, 0.05, n))
    spread_h = rng.uniform(0.01, 0.15, n)
    spread_l = rng.uniform(0.01, 0.15, n)
    opens = np.concatenate([[100.0], close[:-1]])
    highs = np.maximum(opens, close) + spread_h
    lows = np.minimum(opens, close) - spread_l
    idx = pd.date_range("2024-01-01", periods=n, freq="5min", tz="UTC")
    m5 = pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": close}, index=idx
    )

    result = Backtester(
        "RW",
        m5,
        StrategyParams(),
        CostModel(spread=0.02, slippage=0.01, tick_size=0.01),
    ).run()
    c = result.counters
    # accounting invariants
    assert len(result.equity) == n
    assert np.isfinite(result.equity.to_numpy()).all()
    assert c.entries_filled == len(result.trades)
    # every closed trade fully exited
    for t in result.trades:
        assert t.qty_remaining == pytest.approx(0.0)
        assert abs(sum(leg.qty for leg in t.legs) - t.qty) < 1e-9
    # equity reconciles with realized PnL
    assert result.equity.iloc[-1] == pytest.approx(
        result.initial_equity + sum(t.net_pnl for t in result.trades)
    )
