from types import SimpleNamespace

from engine.entries import EXPIRED, FILLED, WAITING, PendingOrder


def c(o, h, l, cl):
    return SimpleNamespace(open=o, high=h, low=l, close=cl)


def test_bullish_limit_fills_when_price_retraces_down():
    order = PendingOrder(direction="bullish", price=100.0, lifetime=5)
    assert order.on_candle(c(102, 103, 101, 102.5)) == (WAITING, None)
    status, fill = order.on_candle(c(101, 101.5, 99.5, 100.2))
    assert status == FILLED and fill == 100.0


def test_bearish_limit_fills_when_price_retraces_up():
    order = PendingOrder(direction="bearish", price=100.0, lifetime=5)
    status, fill = order.on_candle(c(99, 100.4, 98.5, 99.2))
    assert status == FILLED and fill == 100.0


def test_gap_through_fills_at_open():
    order = PendingOrder(direction="bullish", price=100.0, lifetime=5)
    status, fill = order.on_candle(c(99.0, 99.5, 98.0, 99.2))  # opens below limit
    assert status == FILLED and fill == 99.0  # price improvement


def test_expiry_after_lifetime_candles():
    order = PendingOrder(direction="bullish", price=100.0, lifetime=3)
    away = c(102, 103, 101, 102)
    assert order.on_candle(away) == (WAITING, None)
    assert order.on_candle(away) == (WAITING, None)
    status, _ = order.on_candle(away)
    assert status == EXPIRED
    # once expired, stays expired
    assert order.on_candle(c(101, 101, 99, 100))[0] == EXPIRED
