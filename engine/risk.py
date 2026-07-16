"""Stop and target calculations.

Per Functional Requirements 5 and the setup description:

    Stop loss (bearish):  trigger_high + stop_buffer_atr * ATR_LTF
    Stop loss (bullish):  trigger_low  - stop_buffer_atr * ATR_LTF
    Target:               opposite side of the swept HTF range
                          (bearish -> prev_low, bullish -> prev_high)
    R = |entry - stop|

The ATR buffer uses the LTF (M5) ATR value as of MSS confirmation — a fully
closed-bar quantity. All levels are rounded to the instrument tick size.
"""

from dataclasses import dataclass

from .crt import CrtSignal


@dataclass(frozen=True)
class TradeLevels:
    entry: float
    stop: float
    target: float
    r_dist: float  # |entry - stop| in price units


def round_to_tick(price: float, tick_size: float) -> float:
    if tick_size <= 0:
        return price
    return round(round(price / tick_size) * tick_size, 10)


def build_trade_levels(
    signal: CrtSignal,
    entry_price: float,
    atr_ltf: float,
    stop_buffer_atr: float,
    tick_size: float,
) -> TradeLevels | None:
    """Compute entry/stop/target. Returns None if the geometry is invalid
    (entry on the wrong side of the stop, or no room to the target)."""
    buffer = stop_buffer_atr * atr_ltf

    if signal.direction == "bearish":
        stop = signal.trigger_high + buffer
        target = signal.prev_low
    else:
        stop = signal.trigger_low - buffer
        target = signal.prev_high

    entry = round_to_tick(entry_price, tick_size)
    stop = round_to_tick(stop, tick_size)
    target = round_to_tick(target, tick_size)

    if signal.direction == "bearish":
        valid = target < entry < stop
    else:
        valid = stop < entry < target
    if not valid:
        return None

    r_dist = abs(entry - stop)
    if r_dist <= 0:
        return None
    return TradeLevels(entry=entry, stop=stop, target=target, r_dist=r_dist)


def partial_levels(
    levels: TradeLevels, direction: str, first_rr: float, second_rr: float
) -> tuple[float, float]:
    """Price levels for the first and second partial exits (1R / 2R by default)."""
    sign = -1.0 if direction == "bearish" else 1.0
    p1 = levels.entry + sign * first_rr * levels.r_dist
    p2 = levels.entry + sign * second_rr * levels.r_dist
    return p1, p2
