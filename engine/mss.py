"""Lower timeframe Market Structure Shift (MSS) confirmation.

After a completed HTF CRT trigger (Functional Requirements 2):

- The reference level is built from the first `reference_candle_count`
  completed M5 candles after the H1 close:
    bearish setup -> reference low  = min(low)  of those candles
    bullish setup -> reference high = max(high) of those candles
- From the next candle onward, MSS is confirmed when a candle CLOSES beyond
  the reference (bearish: close < reference low; bullish: close > reference
  high).
- If no confirmation occurs within `mss_lookback` scanned M5 candles in
  total, the setup is invalidated.

No trade is permitted before MSS confirmation.
"""

from dataclasses import dataclass, field

PENDING = "pending"
CONFIRMED = "confirmed"
INVALIDATED = "invalidated"


@dataclass
class MssTracker:
    direction: str  # "bearish" | "bullish"
    reference_candle_count: int
    mss_lookback: int
    reference: float | None = None
    candles: list = field(default_factory=list)  # closed M5 candles scanned
    count: int = 0
    status: str = PENDING

    def on_candle_close(self, candle) -> str:
        """Feed one completed M5 candle. Returns the tracker status.

        `candle` is any object with open/high/low/close attributes (a
        pandas Series row works via [] access; a namedtuple via attributes).
        """
        if self.status != PENDING:
            return self.status

        self.count += 1
        self.candles.append(candle)
        high = float(candle.high)
        low = float(candle.low)
        close = float(candle.close)

        if self.count <= self.reference_candle_count:
            # Building the reference from the first N candles.
            if self.direction == "bearish":
                self.reference = (
                    low if self.reference is None else min(self.reference, low)
                )
            else:
                self.reference = (
                    high if self.reference is None else max(self.reference, high)
                )
        else:
            # Confirmation phase.
            if self.direction == "bearish" and close < self.reference:
                self.status = CONFIRMED
                return self.status
            if self.direction == "bullish" and close > self.reference:
                self.status = CONFIRMED
                return self.status

        if self.count >= self.mss_lookback:
            self.status = INVALIDATED
        return self.status
