import pandas as pd
import pytest

from engine.crt import CrtSignal
from engine.execution import CostModel
from engine.risk import build_trade_levels, partial_levels, round_to_tick
from engine.states import InvalidTransition, State, StateMachine

T = pd.Timestamp("2024-01-01 10:00", tz="UTC")


def bearish_signal():
    return CrtSignal(
        "bearish",
        T,
        trigger_high=110.0,
        trigger_low=104.0,
        prev_high=109.0,
        prev_low=100.0,
    )


def bullish_signal():
    return CrtSignal(
        "bullish",
        T,
        trigger_high=106.0,
        trigger_low=99.0,
        prev_high=110.0,
        prev_low=100.0,
    )


def test_bearish_levels():
    lv = build_trade_levels(
        bearish_signal(),
        entry_price=107.0,
        atr_ltf=2.0,
        stop_buffer_atr=0.1,
        tick_size=0.01,
    )
    assert lv.stop == pytest.approx(110.2)  # trigger_high + 0.1 * ATR
    assert lv.target == 100.0  # opposite side of swept range
    assert lv.r_dist == pytest.approx(3.2)
    p1, p2 = partial_levels(lv, "bearish", 1.0, 2.0)
    assert p1 == pytest.approx(107.0 - 3.2) and p2 == pytest.approx(107.0 - 6.4)


def test_bullish_levels():
    lv = build_trade_levels(
        bullish_signal(),
        entry_price=103.0,
        atr_ltf=2.0,
        stop_buffer_atr=0.1,
        tick_size=0.01,
    )
    assert lv.stop == pytest.approx(98.8)
    assert lv.target == 110.0
    p1, _ = partial_levels(lv, "bullish", 1.0, 2.0)
    assert p1 == pytest.approx(103.0 + 4.2)


def test_invalid_geometry_returns_none():
    # entry beyond the stop
    assert build_trade_levels(bearish_signal(), 111.0, 2.0, 0.1, 0.01) is None
    # entry beyond the target (no room for profit)
    assert build_trade_levels(bearish_signal(), 99.0, 2.0, 0.1, 0.01) is None


def test_round_to_tick():
    assert round_to_tick(1.234567, 0.00001) == pytest.approx(1.23457)
    assert round_to_tick(1.234567, 0.0) == 1.234567


def test_cost_model_adverse_fills():
    cm = CostModel(spread=0.0002, slippage=0.0001, commission_per_unit_side=0.00003)
    assert cm.fill_price(1.1000, "buy") == pytest.approx(1.1000 + 0.0001 + 0.0001)
    assert cm.fill_price(1.1000, "sell") == pytest.approx(1.1000 - 0.0002)
    assert cm.commission(100_000) == pytest.approx(3.0)
    assert cm.spread_cost(100_000) == pytest.approx(10.0)


def test_state_machine_enforces_transitions():
    fsm = StateMachine()
    fsm.to(State.AWAITING_MSS)
    fsm.to(State.AWAITING_RETRACEMENT)
    fsm.to(State.ACTIVE_TRADE)
    with pytest.raises(InvalidTransition):
        fsm.to(State.AWAITING_MSS)  # active trade can only close
    fsm.to(State.CLOSED)
    fsm.to(State.IDLE)
    with pytest.raises(InvalidTransition):
        fsm.to(State.ACTIVE_TRADE)  # no market entries from idle
