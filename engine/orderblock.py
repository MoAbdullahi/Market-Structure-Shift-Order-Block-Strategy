"""Order Block identification.

After MSS confirmation (Functional Requirements 3): locate the final
opposite-colored M5 candle immediately preceding the impulsive break.

    bearish setup -> last bullish candle (close > open)
    bullish setup -> last bearish candle (close < open)

The candle BODY defines the Order Block. The entry price is configurable:
midpoint | open | close | body_high | body_low.
"""

from dataclasses import dataclass

PRICING_MODES = ("midpoint", "open", "close", "body_high", "body_low")


@dataclass(frozen=True)
class OrderBlock:
    time: object  # timestamp of the OB candle
    open: float
    close: float
    body_high: float
    body_low: float

    def entry_price(self, mode: str = "midpoint") -> float:
        if mode == "midpoint":
            return (self.body_high + self.body_low) / 2.0
        if mode == "open":
            return self.open
        if mode == "close":
            return self.close
        if mode == "body_high":
            return self.body_high
        if mode == "body_low":
            return self.body_low
        raise ValueError(f"unknown ob_pricing mode: {mode!r}")


def find_order_block(candles, direction: str) -> OrderBlock | None:
    """Find the OB among the scanned M5 candles preceding the MSS break.

    `candles` must be the closed candles from the first scanned M5 candle up
    to and INCLUDING the MSS confirmation candle; the confirmation candle
    itself (the impulsive break) is excluded from the search.

    Returns None when no opposite-colored candle exists (setup discarded).
    """
    search = candles[:-1]  # exclude the MSS confirmation candle
    for candle in reversed(search):
        o = float(candle.open)
        c = float(candle.close)
        if direction == "bearish" and c > o:  # last bullish candle
            return _make_ob(candle, o, c)
        if direction == "bullish" and c < o:  # last bearish candle
            return _make_ob(candle, o, c)
    return None


def _make_ob(candle, o: float, c: float) -> OrderBlock:
    return OrderBlock(
        time=getattr(candle, "Index", getattr(candle, "name", None)),
        open=o,
        close=c,
        body_high=max(o, c),
        body_low=min(o, c),
    )
