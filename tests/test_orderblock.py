from types import SimpleNamespace

import pytest

from engine.orderblock import find_order_block


def c(o, cl, ts=None):
    return SimpleNamespace(
        open=o, high=max(o, cl) + 0.5, low=min(o, cl) - 0.5, close=cl, Index=ts
    )


def test_bearish_ob_is_last_bullish_candle_before_break():
    candles = [
        c(100, 101, "a"),  # bullish
        c(101, 100.5, "b"),  # bearish
        c(100.5, 101.5, "c"),  # bullish  <- the OB
        c(101.5, 99.0, "d"),  # MSS break candle (excluded)
    ]
    ob = find_order_block(candles, "bearish")
    assert ob is not None and ob.time == "c"
    assert ob.body_low == 100.5 and ob.body_high == 101.5


def test_bullish_ob_is_last_bearish_candle_before_break():
    candles = [
        c(100, 99.5, "a"),  # bearish <- the OB
        c(99.5, 102.0, "b"),  # MSS break candle (excluded)
    ]
    ob = find_order_block(candles, "bullish")
    assert ob is not None and ob.time == "a"


def test_no_opposite_candle_returns_none():
    candles = [c(100, 99.5), c(99.5, 99.0), c(99.0, 98.0)]  # all bearish
    assert find_order_block(candles, "bearish") is None


def test_doji_is_not_opposite_colored():
    candles = [c(100, 100), c(100, 99.0)]
    assert find_order_block(candles, "bearish") is None


def test_entry_pricing_modes():
    ob = find_order_block([c(100, 102, "x"), c(102, 98, "y")], "bearish")
    assert ob.entry_price("midpoint") == pytest.approx(101.0)
    assert ob.entry_price("open") == 100.0
    assert ob.entry_price("close") == 102.0
    assert ob.entry_price("body_high") == 102.0
    assert ob.entry_price("body_low") == 100.0
    with pytest.raises(ValueError):
        ob.entry_price("nope")
