"""Trade management: staged partial exits and dynamic stop movement.

Exit Scheme A (Functional Requirements 6 / setup description):
    50% of the position exits at 1R
    30% exits at 2R
    20% rides to the HTF target (opposite side of the swept range)

Stop management:
    after the first partial  -> stop moves to breakeven (raw entry level)
    after the second partial -> stop moves to the 1R level

Intrabar rules (deterministic, configurable):
    - `intrabar_priority: stop_first` (default, conservative): when a candle's
      range touches both the current stop and an exit level, the stop is
      assumed to have been hit first.
    - Stop moves triggered by a partial take effect on the NEXT candle (the
      sequence of touches inside one M5 candle is unknowable from OHLC).
    - Gap handling: a level gapped through at the open fills at the open.

All exit fills are cost-adjusted through the CostModel; R multiples are
reported net of costs against the initial risk (qty * r_dist).
"""

from dataclasses import dataclass, field

from .execution import CostModel

OPEN = "open"
CLOSED_STATUS = "closed"


@dataclass
class ExitLeg:
    time: object
    reason: str  # "partial_1" | "partial_2" | "target" | "stop" | "end_of_data"
    qty: float
    raw_price: float
    fill_price: float
    pnl: float  # currency, net of this leg's costs


@dataclass
class Trade:
    symbol: str
    direction: str  # "bearish" (short) | "bullish" (long)
    entry_time: object
    entry_raw: float  # OB limit level
    entry_fill: float  # cost-adjusted fill
    qty: float
    stop_initial: float
    target: float
    r_dist: float
    cost_model: CostModel
    partial_fractions: tuple = (0.5, 0.3, 0.2)
    first_rr: float = 1.0
    second_rr: float = 2.0
    intrabar_priority: str = "stop_first"
    move_stop_to_breakeven_after: int = 1  # after Nth partial
    trail_stop_to_1r_after: int = 2

    status: str = OPEN
    stop_current: float = field(init=False)
    partials_done: int = 0
    legs: list = field(default_factory=list)
    bars_in_trade: int = 0
    exit_time: object = None
    commission_paid: float = 0.0
    spread_cost: float = 0.0
    slippage_cost: float = 0.0

    def __post_init__(self):
        self.stop_current = self.stop_initial
        sign = self._sign
        self.p1_level = self.entry_raw + sign * self.first_rr * self.r_dist
        self.p2_level = self.entry_raw + sign * self.second_rr * self.r_dist
        self.qty_remaining = self.qty
        # entry costs (entry side: long buys, short sells)
        entry_side = "buy" if self.direction == "bullish" else "sell"
        self._entry_commission = self.cost_model.commission(self.qty)
        self.commission_paid += self._entry_commission
        self.spread_cost += self.cost_model.spread_cost(self.qty)
        self.slippage_cost += self.cost_model.slippage_cost(self.qty)
        self._entry_side = entry_side

    # ------------------------------------------------------------------ #
    @property
    def _sign(self) -> float:
        """+1 for long (bullish), -1 for short (bearish)."""
        return 1.0 if self.direction == "bullish" else -1.0

    @property
    def _exit_side(self) -> str:
        return "sell" if self.direction == "bullish" else "buy"

    @property
    def risk_amount(self) -> float:
        return self.qty * self.r_dist

    @property
    def net_pnl(self) -> float:
        # leg PnLs already carry exit-side commission; entry-side commission
        # is deducted here once
        return sum(leg.pnl for leg in self.legs) - self._entry_commission

    @property
    def realized_r(self) -> float:
        return self.net_pnl / self.risk_amount if self.risk_amount > 0 else 0.0

    # ------------------------------------------------------------------ #
    def on_candle(self, candle, time) -> str:
        """Manage the trade over one M5 candle. Returns trade status."""
        if self.status != OPEN:
            return self.status
        self.bars_in_trade += 1

        o = float(candle.open)
        h = float(candle.high)
        low = float(candle.low)

        stop_at_entry = self.stop_current  # stop moves apply from next candle
        checks = self._ordered_checks(stop_at_entry)
        for kind, level in checks:
            if self.status != OPEN:
                break
            if kind == "stop":
                if self._touched_adverse(o, h, low, level):
                    raw = self._gap_price_adverse(o, level)
                    self._exit(self.qty_remaining, raw, "stop", time)
            else:
                if self._touched_favorable(o, h, low, level):
                    raw = self._gap_price_favorable(o, level)
                    self._take_profit(kind, raw, time)
        return self.status

    def close_at(self, raw_price: float, time, reason: str = "end_of_data") -> None:
        """Force-close remaining position (end of data)."""
        if self.status == OPEN and self.qty_remaining > 0:
            self._exit(self.qty_remaining, raw_price, reason, time)

    # ------------------------------------------------------------------ #
    def _ordered_checks(self, stop_level):
        profit_checks = []
        if self.partials_done < 1:
            profit_checks.append(("partial_1", self.p1_level))
        if self.partials_done < 2:
            profit_checks.append(("partial_2", self.p2_level))
        profit_checks.append(("target", self.target))
        if self.intrabar_priority == "stop_first":
            return [("stop", stop_level)] + profit_checks
        return profit_checks + [("stop", stop_level)]

    def _touched_adverse(self, o, h, low, level) -> bool:
        # stop for a long is below (low <= level); for a short above (high >= level)
        return low <= level if self.direction == "bullish" else h >= level

    def _touched_favorable(self, o, h, low, level) -> bool:
        # profit level for a long is above (high >= level); for a short below
        return h >= level if self.direction == "bullish" else low <= level

    def _gap_price_adverse(self, o, level) -> float:
        # stop order: if the candle opens beyond the stop, fill at the open
        if self.direction == "bullish":
            return o if o <= level else level
        return o if o >= level else level

    def _gap_price_favorable(self, o, level) -> float:
        # profit exit: an open gapped beyond the level fills at the (better) open
        if self.direction == "bullish":
            return o if o >= level else level
        return o if o <= level else level

    def _take_profit(self, kind: str, raw_price: float, time) -> None:
        if kind == "partial_1":
            qty = self.partial_fractions[0] * self.qty
            self._exit(qty, raw_price, "partial_1", time, partial=True)
            self.partials_done = 1
            if self.move_stop_to_breakeven_after == 1:
                self.stop_current = self.entry_raw
        elif kind == "partial_2":
            qty = self.partial_fractions[1] * self.qty
            self._exit(qty, raw_price, "partial_2", time, partial=True)
            self.partials_done = 2
            if self.trail_stop_to_1r_after == 2:
                self.stop_current = self.p1_level
        else:  # final target
            self._exit(self.qty_remaining, raw_price, "target", time)

    def _exit(
        self, qty: float, raw_price: float, reason: str, time, partial: bool = False
    ) -> None:
        qty = min(qty, self.qty_remaining)
        if qty <= 0:
            return
        fill = self.cost_model.fill_price(raw_price, self._exit_side)
        commission = self.cost_model.commission(qty)
        pnl = self._sign * (fill - self.entry_fill) * qty - commission
        self.commission_paid += commission
        self.spread_cost += self.cost_model.spread_cost(qty)
        self.slippage_cost += self.cost_model.slippage_cost(qty)
        self.legs.append(
            ExitLeg(
                time=time,
                reason=reason,
                qty=qty,
                raw_price=raw_price,
                fill_price=fill,
                pnl=pnl,
            )
        )
        self.qty_remaining -= qty
        if not partial or self.qty_remaining <= 1e-12:
            self.qty_remaining = max(self.qty_remaining, 0.0)
            if self.qty_remaining == 0.0 or not partial:
                self.status = CLOSED_STATUS
                self.exit_time = time

    # ------------------------------------------------------------------ #
    def unrealized_pnl(self, mark_price: float) -> float:
        if self.qty_remaining <= 0:
            return 0.0
        return self._sign * (mark_price - self.entry_fill) * self.qty_remaining
