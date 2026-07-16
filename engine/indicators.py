"""ATR calculations (Wilder's smoothing).

All indicator series are causal: the value at index i uses only bars <= i,
so precomputing them over the full dataset introduces no look-ahead bias as
long as the value at i is only consumed after bar i has closed.
"""

import pandas as pd


def true_range(df: pd.DataFrame) -> pd.Series:
    """True Range per bar: max(H-L, |H-prevC|, |L-prevC|)."""
    prev_close = df["close"].shift(1)
    ranges = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    )
    return ranges.max(axis=1)


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Wilder's Average True Range.

    Uses the recursive smoothing ATR_t = ATR_{t-1} + (TR_t - ATR_{t-1})/period,
    which is an EMA with alpha = 1/period. NaN until `period` bars have closed.
    """
    tr = true_range(df)
    return tr.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
