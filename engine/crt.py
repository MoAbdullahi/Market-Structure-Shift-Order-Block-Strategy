"""Higher timeframe CRT (Candle Range Theory) detection.

Every completed H1 candle is evaluated against the previous completed H1
candle (Implementation Task Report, Functional Requirements 1):

Bearish CRT:  cur.high > prev.high  AND  cur.close < prev.high
Bullish CRT:  cur.low  < prev.low   AND  cur.close > prev.low
Filter:       (prev.high - prev.low) >= min_atr_ratio * ATR(atr_period) at prev

Optional Strong Filter (setup parameter, OFF by default): the trigger candle
must additionally close beyond the midpoint of the previous candle's range
(bearish: close below midpoint; bullish: close above midpoint).
"""

import math
from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class CrtSignal:
    direction: str  # "bearish" | "bullish"
    trigger_time: pd.Timestamp  # open time of the trigger H1 candle
    trigger_high: float
    trigger_low: float
    prev_high: float
    prev_low: float


def evaluate_crt(
    prev: pd.Series,
    cur: pd.Series,
    prev_atr: float,
    cur_time: pd.Timestamp,
    min_atr_ratio: float = 0.5,
    strong_filter: bool = False,
) -> CrtSignal | None:
    """Evaluate one completed H1 candle pair. Returns a CrtSignal or None.

    `prev_atr` is the H1 ATR value as of the previous candle's close — every
    input is known the moment the trigger candle completes.
    A candle that sweeps BOTH sides and closes back inside is ambiguous and
    produces no signal.
    """
    if prev_atr is None or math.isnan(prev_atr):
        return None
    if (prev["high"] - prev["low"]) < min_atr_ratio * prev_atr:
        return None

    bearish = cur["high"] > prev["high"] and cur["close"] < prev["high"]
    bullish = cur["low"] < prev["low"] and cur["close"] > prev["low"]
    if bearish == bullish:  # neither, or ambiguous double sweep
        return None

    if strong_filter:
        midpoint = (prev["high"] + prev["low"]) / 2.0
        if bearish and not cur["close"] < midpoint:
            return None
        if bullish and not cur["close"] > midpoint:
            return None

    return CrtSignal(
        direction="bearish" if bearish else "bullish",
        trigger_time=cur_time,
        trigger_high=float(cur["high"]),
        trigger_low=float(cur["low"]),
        prev_high=float(prev["high"]),
        prev_low=float(prev["low"]),
    )
