"""Execution cost modeling (Required Improvements 4).

Bar prices are treated as mid prices. Every fill is adjusted adversely:

    buy  fill = raw + spread/2 + slippage
    sell fill = raw - spread/2 - slippage

so a round trip pays the full configured spread plus slippage on each side.
Commission is charged per side, per unit of position size, in account
currency. All values are configurable per instrument.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class CostModel:
    spread: float = 0.0  # full bid-ask spread, price units
    slippage: float = 0.0  # adverse slippage per side, price units
    commission_per_unit_side: float = 0.0  # account currency per unit, per side
    tick_size: float = 0.0

    @property
    def round_trip_cost(self) -> float:
        """Total adverse cost of entry + exit for one unit, in price units
        (commission is account currency per unit, which is price-equivalent)."""
        return self.spread + 2.0 * self.slippage + 2.0 * self.commission_per_unit_side

    def fill_price(self, raw_price: float, side: str) -> float:
        """Adverse-adjusted execution price. side: 'buy' | 'sell'."""
        adjustment = self.spread / 2.0 + self.slippage
        if side == "buy":
            return raw_price + adjustment
        if side == "sell":
            return raw_price - adjustment
        raise ValueError(f"unknown side: {side!r}")

    def spread_cost(self, qty: float) -> float:
        """Currency cost of the half-spread paid on one side."""
        return (self.spread / 2.0) * qty

    def slippage_cost(self, qty: float) -> float:
        return self.slippage * qty

    def commission(self, qty: float) -> float:
        """Currency commission for one side."""
        return self.commission_per_unit_side * qty
