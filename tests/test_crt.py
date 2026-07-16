import pandas as pd
import pytest

from engine.crt import evaluate_crt

T = pd.Timestamp("2024-01-01 10:00", tz="UTC")


def candle(o, h, l, c):
    return pd.Series({"open": o, "high": h, "low": l, "close": c})


PREV = candle(100.0, 110.0, 100.0, 105.0)  # range 10


def test_bearish_crt_detected():
    cur = candle(105.0, 112.0, 104.0, 108.0)  # sweeps high, closes back below
    sig = evaluate_crt(PREV, cur, prev_atr=10.0, cur_time=T, min_atr_ratio=0.5)
    assert sig is not None and sig.direction == "bearish"
    assert sig.trigger_high == 112.0
    assert sig.prev_high == 110.0 and sig.prev_low == 100.0


def test_bullish_crt_detected():
    cur = candle(105.0, 106.0, 98.0, 103.0)  # sweeps low, closes back above
    sig = evaluate_crt(PREV, cur, prev_atr=10.0, cur_time=T)
    assert sig is not None and sig.direction == "bullish"


def test_no_signal_when_close_beyond_swept_level():
    cur = candle(
        105.0, 112.0, 104.0, 111.0
    )  # closes above prev high: breakout, not CRT
    assert evaluate_crt(PREV, cur, prev_atr=10.0, cur_time=T) is None


def test_atr_range_filter_rejects_small_previous_candle():
    cur = candle(105.0, 112.0, 104.0, 108.0)
    # prev range 10 < 0.5 * ATR 25
    assert evaluate_crt(PREV, cur, prev_atr=25.0, cur_time=T, min_atr_ratio=0.5) is None
    # exactly at the threshold passes (>=)
    assert (
        evaluate_crt(PREV, cur, prev_atr=20.0, cur_time=T, min_atr_ratio=0.5)
        is not None
    )


def test_ambiguous_double_sweep_produces_no_signal():
    cur = candle(105.0, 112.0, 98.0, 105.0)  # sweeps both sides, closes inside
    assert evaluate_crt(PREV, cur, prev_atr=10.0, cur_time=T) is None


def test_nan_atr_produces_no_signal():
    cur = candle(105.0, 112.0, 104.0, 108.0)
    assert evaluate_crt(PREV, cur, prev_atr=float("nan"), cur_time=T) is None


@pytest.mark.parametrize(
    "close,expected",
    [(108.0, None), (104.0, "bearish")],  # midpoint of prev range = 105
)
def test_strong_filter_requires_midpoint_close(close, expected):
    cur = candle(105.0, 112.0, 103.0, close)
    sig = evaluate_crt(PREV, cur, prev_atr=10.0, cur_time=T, strong_filter=True)
    assert (sig.direction if sig else None) == expected
