from types import SimpleNamespace

import pytest

from engine.execution import CostModel
from engine.trade import CLOSED_STATUS, OPEN, Trade

NO_COST = CostModel()


def c(o, h, l, cl):
    return SimpleNamespace(open=o, high=h, low=l, close=cl)


def make_short(entry=100.0, stop=104.0, target=88.0, qty=100.0, cost_model=NO_COST):
    return Trade(
        symbol="TEST",
        direction="bearish",
        entry_time=0,
        entry_raw=entry,
        entry_fill=cost_model.fill_price(entry, "sell"),
        qty=qty,
        stop_initial=stop,
        target=target,
        r_dist=abs(entry - stop),
        cost_model=cost_model,
    )


def test_full_scheme_a_short():
    # R = 4 -> partials at 96 (1R) and 92 (2R), final target 88
    t = make_short()
    assert t.on_candle(c(99, 100, 95.5, 96), 1) == OPEN  # hits 1R
    assert t.partials_done == 1
    assert t.stop_current == 100.0  # breakeven after first partial
    assert t.on_candle(c(96, 96.5, 91.5, 92), 2) == OPEN  # hits 2R
    assert t.partials_done == 2
    assert t.stop_current == 96.0  # trails to the 1R level
    assert t.on_candle(c(92, 92.5, 87.5, 88), 3) == CLOSED_STATUS  # target
    # legs: 50 @ 1R + 30 @ 2R + 20 @ 3R = 50*4 + 30*8 + 20*12 = 680
    assert t.net_pnl == pytest.approx(50 * 4 + 30 * 8 + 20 * 12)
    assert t.realized_r == pytest.approx(680 / 400)


def test_straight_stop_loss_is_minus_one_r():
    t = make_short()
    assert t.on_candle(c(101, 104.5, 100.5, 104), 1) == CLOSED_STATUS
    assert t.realized_r == pytest.approx(-1.0)
    assert t.legs[0].reason == "stop"


def test_breakeven_after_first_partial():
    t = make_short()
    t.on_candle(c(99, 100, 95.5, 96), 1)  # partial 1, stop -> 100
    status = t.on_candle(c(96, 100.5, 95, 100), 2)  # rallies back to breakeven
    assert status == CLOSED_STATUS
    assert t.legs[-1].reason == "stop"
    # 50% banked 4 points, 50% flat at breakeven
    assert t.net_pnl == pytest.approx(50 * 4)
    assert t.realized_r == pytest.approx(0.5)


def test_trail_to_1r_after_second_partial():
    t = make_short()
    t.on_candle(c(99, 100, 95.5, 96), 1)
    t.on_candle(c(96, 96.5, 91.5, 92), 2)
    status = t.on_candle(c(92, 96.5, 91.8, 96), 3)  # pulls back to the 1R level
    assert status == CLOSED_STATUS
    # 50@4 + 30@8 + 20@4 (stopped at 96) = 520
    assert t.net_pnl == pytest.approx(520)


def test_stop_first_priority_when_both_touched():
    t = make_short()
    # one candle spans both the stop (104) and the 1R level (96): stop wins
    assert t.on_candle(c(100, 104.5, 95, 100), 1) == CLOSED_STATUS
    assert t.legs[0].reason == "stop"
    assert t.realized_r == pytest.approx(-1.0)


def test_stop_move_applies_next_candle_not_same_candle():
    t = make_short()
    # candle hits 1R (96) AND returns to entry (100) within the same candle;
    # with stop_first the OLD stop (104) is checked first and not touched,
    # the partial fills, and the breakeven stop only applies from next candle.
    assert t.on_candle(c(99, 100.2, 95.5, 100), 1) == OPEN
    assert t.partials_done == 1
    assert t.qty_remaining == pytest.approx(50)


def test_gap_through_stop_fills_at_open():
    t = make_short()
    assert t.on_candle(c(105, 106, 104.5, 105.5), 1) == CLOSED_STATUS
    assert t.legs[0].raw_price == 105  # gapped open, worse than the stop
    assert t.realized_r < -1.0


def test_multiple_levels_in_one_candle():
    t = make_short()
    # candle sweeps from entry to below target without touching the stop
    assert t.on_candle(c(99, 99.5, 87, 87.5), 1) == CLOSED_STATUS
    assert [leg.reason for leg in t.legs] == ["partial_1", "partial_2", "target"]


def test_long_side_mirror():
    t = Trade(
        symbol="TEST",
        direction="bullish",
        entry_time=0,
        entry_raw=100.0,
        entry_fill=100.0,
        qty=100.0,
        stop_initial=96.0,
        target=112.0,
        r_dist=4.0,
        cost_model=NO_COST,
    )
    t.on_candle(c(101, 104.5, 100.5, 104), 1)  # 1R = 104
    assert t.partials_done == 1 and t.stop_current == 100.0
    t.on_candle(c(104, 108.5, 103.5, 108), 2)  # 2R = 108
    assert t.stop_current == 104.0
    assert t.on_candle(c(108, 112.5, 107.5, 112), 3) == CLOSED_STATUS
    assert t.realized_r == pytest.approx((50 * 4 + 30 * 8 + 20 * 12) / 400)


def test_costs_reduce_pnl():
    cm = CostModel(spread=0.2, slippage=0.1, commission_per_unit_side=0.01)
    t = make_short(cost_model=cm)
    t.on_candle(c(101, 104.5, 100.5, 104), 1)  # straight stop
    # gross -1R minus entry/exit costs
    assert t.realized_r < -1.0
    assert t.commission_paid > 0 and t.spread_cost > 0 and t.slippage_cost > 0


def test_entry_commission_deducted_from_net_pnl():
    cm = CostModel(commission_per_unit_side=0.01)  # no spread/slippage
    t = make_short(cost_model=cm)
    t.on_candle(c(101, 104.5, 100.5, 104), 1)  # straight stop: gross -1R = -400
    # qty 100: entry commission 1.0 + exit commission 1.0
    assert t.net_pnl == pytest.approx(-400 - 2.0)
    assert t.commission_paid == pytest.approx(2.0)


def test_end_of_data_force_close():
    t = make_short()
    t.on_candle(c(99, 100, 98, 99), 1)
    t.close_at(99.0, 2)
    assert t.status == CLOSED_STATUS
    assert t.legs[-1].reason == "end_of_data"
    assert t.net_pnl == pytest.approx(100 * 1.0)
