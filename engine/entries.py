"""Pending limit order management.

After the Order Block is identified, a pending limit order is placed
(Functional Requirements 4). The position opens only if price revisits the
Order Block level — no market entries.

Each pending order has a configurable lifetime measured in completed M5
candles (Required Improvements 2). If the level is not revisited within
`lifetime` candles, the order is canceled and the strategy returns to Idle.

Fill model (standard limit-order semantics, evaluated on each M5 candle):
    bullish (buy limit below market):
        open <= price -> filled at open (gap through, price improvement)
        low  <= price -> filled at the limit price
    bearish (sell limit above market):
        open >= price -> filled at open
        high >= price -> filled at the limit price
"""

from dataclasses import dataclass

WAITING = "waiting"
FILLED = "filled"
EXPIRED = "expired"


@dataclass
class PendingOrder:
    direction: str  # "bearish" | "bullish"
    price: float  # OB limit level
    lifetime: int  # max completed M5 candles before cancellation
    age: int = 0
    status: str = WAITING

    def on_candle(self, candle) -> tuple[str, float | None]:
        """Feed one M5 candle. Returns (status, raw_fill_price | None)."""
        if self.status != WAITING:
            return self.status, None

        o = float(candle.open)
        h = float(candle.high)
        low = float(candle.low)

        if self.direction == "bullish":
            if o <= self.price:
                return self._fill(o)
            if low <= self.price:
                return self._fill(self.price)
        else:
            if o >= self.price:
                return self._fill(o)
            if h >= self.price:
                return self._fill(self.price)

        self.age += 1
        if self.age >= self.lifetime:
            self.status = EXPIRED
            return self.status, None
        return WAITING, None

    def _fill(self, raw_price: float) -> tuple[str, float]:
        self.status = FILLED
        return FILLED, raw_price
