"""Strategy orchestration: wires CRT -> MSS -> Order Block -> pending entry
-> trade management through the finite state machine.

Time synchronization (Required Improvements 1):
    - CRT signals are generated only when the H1 candle has CLOSED. The
      backtester raises the `h1_completed` event before processing the first
      M5 candle of the new hour, so M5 scanning starts with the first
      completed M5 candle after the H1 close.
    - MSS reference candles are the first `reference_candle_count` completed
      M5 candles after that moment.

Setup filters (all externally configured; setup #1 runs them OFF except MSS
confirmation which is always mandatory):
    - session filter: trigger accepted only if the H1 close time falls inside
      one of the configured UTC session windows.
    - news filter: trigger rejected inside configured blackout windows.
    - strong filter: stricter midpoint-close requirement on the CRT candle.
    - premium/discount filter: OB entry must sit in the premium half of the
      swept HTF range for shorts, discount half for longs.
"""

from dataclasses import dataclass, field

from . import crt as crt_mod
from . import mss as mss_mod
from . import orderblock as ob_mod
from .entries import EXPIRED, FILLED, PendingOrder
from .execution import CostModel
from .risk import build_trade_levels, round_to_tick
from .states import State, StateMachine
from .trade import CLOSED_STATUS, Trade


@dataclass
class StrategyParams:
    # indicator
    atr_period_htf: int = 14
    atr_period_ltf: int = 14
    min_atr_ratio: float = 0.5
    stop_buffer_atr: float = 0.1
    # entry
    ob_pricing: str = "midpoint"
    pending_lifetime: int = 24
    mss_lookback: int = 36
    reference_candle_count: int = 3
    # risk / exits
    partial_fractions: tuple = (0.5, 0.3, 0.2)
    first_rr: float = 1.0
    second_rr: float = 2.0
    intrabar_priority: str = "stop_first"
    move_stop_to_breakeven_after: int = 1
    trail_stop_to_1r_after: int = 2
    # sizing
    risk_pct: float = 1.0  # % of current equity risked per trade
    # small-R filter: reject setups whose R distance is below
    # min_r_cost_multiple * round-trip execution cost (0 = off)
    min_r_cost_multiple: float = 0.0
    # session / filters
    session_enabled: bool = False
    session_windows: tuple = ()  # e.g. (("07:00","16:00"),) UTC
    news_blackouts: tuple = ()  # e.g. (("2023-01-05T13:25","2023-01-05T13:40"),)
    strong_filter: bool = False
    pd_filter: bool = False


@dataclass
class Counters:
    crt_triggers: int = 0
    missed_entries: int = 0  # CRT trigger while a setup/trade is in progress
    session_filtered: int = 0
    invalidated_mss: int = 0
    expired_setups: int = 0  # MSS confirmed but no OB / invalid geometry / PD-filtered
    small_r_filtered: int = 0  # setups rejected by the small-R cost filter
    canceled_pending: int = 0
    entries_filled: int = 0


class CrtStrategy:
    """One instance per instrument. Driven bar-by-bar by the backtester."""

    def __init__(self, symbol: str, params: StrategyParams, cost_model: CostModel):
        self.symbol = symbol
        self.p = params
        self.costs = cost_model
        self.fsm = StateMachine()
        self.counters = Counters()
        self.signal = None
        self.mss_tracker = None
        self.pending = None
        self.pending_levels = None
        self.active_trade: Trade | None = None
        self.closed_trades: list[Trade] = []

    # ------------------------------------------------------------------ #
    # H1 event — called by the backtester when an H1 candle completes,
    # BEFORE the first M5 candle of the new hour is processed.
    # ------------------------------------------------------------------ #
    def on_h1_close(self, prev_candle, cur_candle, prev_atr, close_time) -> None:
        signal = crt_mod.evaluate_crt(
            prev_candle,
            cur_candle,
            prev_atr,
            cur_time=close_time,
            min_atr_ratio=self.p.min_atr_ratio,
            strong_filter=self.p.strong_filter,
        )
        if signal is None:
            return
        self.counters.crt_triggers += 1

        if not self.fsm.is_idle:
            self.counters.missed_entries += 1
            return
        if not self._passes_time_filters(close_time):
            self.counters.session_filtered += 1
            return

        self.signal = signal
        self.mss_tracker = mss_mod.MssTracker(
            direction=signal.direction,
            reference_candle_count=self.p.reference_candle_count,
            mss_lookback=self.p.mss_lookback,
        )
        self.fsm.to(State.AWAITING_MSS, close_time)

    # ------------------------------------------------------------------ #
    # M5 events — intrabar management first, then close-based logic.
    # ------------------------------------------------------------------ #
    def on_m5_intrabar(self, candle, time, equity: float) -> None:
        """Order fills and trade management using the candle's range."""
        if self.fsm.state is State.ACTIVE_TRADE:
            self._manage_trade(candle, time)
        elif self.fsm.state is State.AWAITING_RETRACEMENT:
            status, raw_fill = self.pending.on_candle(candle)
            if status == FILLED:
                self._open_trade(raw_fill, time, equity)
                # conservative: manage the trade over the remainder of the
                # fill candle as well (stop-first priority applies)
                self._manage_trade(candle, time)
            elif status == EXPIRED:
                self.counters.canceled_pending += 1
                self._reset(time)

    def on_m5_close(self, candle, time, atr_ltf: float) -> None:
        """MSS tracking and Order Block placement on candle close."""
        if self.fsm.state is not State.AWAITING_MSS:
            return
        status = self.mss_tracker.on_candle_close(candle)
        if status == mss_mod.INVALIDATED:
            self.counters.invalidated_mss += 1
            self._reset(time)
        elif status == mss_mod.CONFIRMED:
            self._place_pending(time, atr_ltf)

    # ------------------------------------------------------------------ #
    def _place_pending(self, time, atr_ltf: float) -> None:
        ob = ob_mod.find_order_block(self.mss_tracker.candles, self.signal.direction)
        if ob is None:
            self.counters.expired_setups += 1
            self._reset(time)
            return

        entry_price = round_to_tick(
            ob.entry_price(self.p.ob_pricing), self.costs.tick_size
        )
        levels = build_trade_levels(
            self.signal,
            entry_price,
            atr_ltf,
            self.p.stop_buffer_atr,
            self.costs.tick_size,
        )
        if levels is None or not self._passes_pd_filter(entry_price):
            self.counters.expired_setups += 1
            self._reset(time)
            return

        if (
            self.p.min_r_cost_multiple > 0
            and levels.r_dist < self.p.min_r_cost_multiple * self.costs.round_trip_cost
        ):
            self.counters.small_r_filtered += 1
            self._reset(time)
            return

        self.pending_levels = levels
        self.pending = PendingOrder(
            direction=self.signal.direction,
            price=levels.entry,
            lifetime=self.p.pending_lifetime,
        )
        self.fsm.to(State.AWAITING_RETRACEMENT, time)

    def _open_trade(self, raw_fill: float, time, equity: float) -> None:
        levels = self.pending_levels
        side = "buy" if self.signal.direction == "bullish" else "sell"
        entry_fill = self.costs.fill_price(raw_fill, side)
        risk_amount = equity * (self.p.risk_pct / 100.0)
        qty = risk_amount / levels.r_dist
        self.active_trade = Trade(
            symbol=self.symbol,
            direction=self.signal.direction,
            entry_time=time,
            entry_raw=raw_fill,
            entry_fill=entry_fill,
            qty=qty,
            stop_initial=levels.stop,
            target=levels.target,
            r_dist=levels.r_dist,
            cost_model=self.costs,
            partial_fractions=tuple(self.p.partial_fractions),
            first_rr=self.p.first_rr,
            second_rr=self.p.second_rr,
            intrabar_priority=self.p.intrabar_priority,
            move_stop_to_breakeven_after=self.p.move_stop_to_breakeven_after,
            trail_stop_to_1r_after=self.p.trail_stop_to_1r_after,
        )
        self.counters.entries_filled += 1
        self.fsm.to(State.ACTIVE_TRADE, time)

    def _manage_trade(self, candle, time) -> None:
        status = self.active_trade.on_candle(candle, time)
        if status == CLOSED_STATUS:
            self._record_closed(time)

    def _record_closed(self, time) -> None:
        self.closed_trades.append(self.active_trade)
        self.fsm.to(State.CLOSED, time)
        self.active_trade = None
        self._reset(time)

    def _reset(self, time) -> None:
        self.signal = None
        self.mss_tracker = None
        self.pending = None
        self.pending_levels = None
        self.fsm.to(State.IDLE, time)

    def finalize(self, last_candle, time) -> None:
        """End of data: force-close any open trade, cancel any pending order."""
        if self.fsm.state is State.ACTIVE_TRADE:
            self.active_trade.close_at(
                float(last_candle.close), time, reason="end_of_data"
            )
            self._record_closed(time)
        elif self.fsm.state is State.AWAITING_RETRACEMENT:
            self.counters.canceled_pending += 1
            self._reset(time)
        elif self.fsm.state is State.AWAITING_MSS:
            self.counters.invalidated_mss += 1
            self._reset(time)

    # ------------------------------------------------------------------ #
    def _passes_time_filters(self, time) -> bool:
        if self.p.session_enabled and self.p.session_windows:
            hhmm = time.strftime("%H:%M")
            in_session = any(
                start <= hhmm < end for start, end in self.p.session_windows
            )
            if not in_session:
                return False
        for start, end in self.p.news_blackouts:
            if str(start) <= time.isoformat() <= str(end):
                return False
        return True

    def _passes_pd_filter(self, entry_price: float) -> bool:
        if not self.p.pd_filter:
            return True
        midpoint = (self.signal.prev_high + self.signal.prev_low) / 2.0
        if self.signal.direction == "bearish":
            return entry_price >= midpoint  # premium half for shorts
        return entry_price <= midpoint  # discount half for longs
