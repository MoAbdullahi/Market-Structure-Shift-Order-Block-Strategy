import numpy as np
import pandas as pd

from engine.indicators import atr, true_range


def make_df(rows):
    idx = pd.date_range("2024-01-01", periods=len(rows), freq="5min", tz="UTC")
    return pd.DataFrame(rows, index=idx, columns=["open", "high", "low", "close"])


def test_true_range_uses_previous_close_gaps():
    df = make_df(
        [
            [10.0, 11.0, 9.0, 10.5],
            [12.0, 12.5, 12.0, 12.2],  # gap up: TR = high - prev_close = 2.0
        ]
    )
    tr = true_range(df)
    assert tr.iloc[0] == 2.0  # first bar: high - low
    assert tr.iloc[1] == 12.5 - 10.5


def test_atr_is_causal_and_wilder_recursive():
    rng = np.random.default_rng(7)
    n = 100
    close = 100 + np.cumsum(rng.normal(0, 1, n))
    high = close + rng.uniform(0.1, 1.0, n)
    low = close - rng.uniform(0.1, 1.0, n)
    df = make_df(np.column_stack([close, high, low, close]))

    period = 14
    full = atr(df, period)
    # causality: ATR at bar i must not change when future bars are removed
    truncated = atr(df.iloc[:50], period)
    assert np.allclose(full.iloc[:50].dropna(), truncated.dropna())
    # NaN until `period` bars have closed
    assert full.iloc[: period - 1].isna().all()
    assert not np.isnan(full.iloc[period - 1])
    # recursive definition holds
    tr = true_range(df)
    expected = full.iloc[20] + (tr.iloc[21] - full.iloc[20]) / period
    assert np.isclose(full.iloc[21], expected)
