from types import SimpleNamespace

from engine.mss import CONFIRMED, INVALIDATED, PENDING, MssTracker


def c(o, h, l, cl):
    return SimpleNamespace(open=o, high=h, low=l, close=cl)


def test_bearish_mss_reference_and_confirmation():
    tr = MssTracker(direction="bearish", reference_candle_count=3, mss_lookback=10)
    # first 3 candles build the reference low = 98
    assert tr.on_candle_close(c(100, 101, 99, 100.5)) == PENDING
    assert tr.on_candle_close(c(100.5, 102, 98, 101)) == PENDING
    assert tr.on_candle_close(c(101, 103, 100, 102)) == PENDING
    assert tr.reference == 98
    # close above reference: still pending; a LOW below reference is not enough
    assert tr.on_candle_close(c(102, 102.5, 97.5, 99)) == PENDING
    # close below reference confirms
    assert tr.on_candle_close(c(99, 99.5, 97, 97.5)) == CONFIRMED
    assert len(tr.candles) == 5


def test_bullish_mss_confirmation():
    tr = MssTracker(direction="bullish", reference_candle_count=2, mss_lookback=10)
    tr.on_candle_close(c(100, 101, 99, 100.5))
    tr.on_candle_close(c(100.5, 102, 100, 101))
    assert tr.reference == 102
    assert tr.on_candle_close(c(101, 103, 100.5, 102.5)) == CONFIRMED


def test_mss_invalidated_after_lookback():
    tr = MssTracker(direction="bearish", reference_candle_count=2, mss_lookback=4)
    tr.on_candle_close(c(100, 101, 99, 100.5))
    tr.on_candle_close(c(100.5, 102, 99.5, 101))
    assert tr.on_candle_close(c(101, 102, 100, 101.5)) == PENDING
    assert tr.on_candle_close(c(101, 102, 100, 101.5)) == INVALIDATED


def test_no_confirmation_inside_reference_window():
    # a close below the running reference during the reference phase must NOT confirm
    tr = MssTracker(direction="bearish", reference_candle_count=3, mss_lookback=10)
    tr.on_candle_close(c(100, 101, 99, 100.5))
    assert tr.on_candle_close(c(100, 100.5, 98, 98.2)) == PENDING  # still building
    assert tr.status == PENDING
