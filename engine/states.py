"""Deterministic strategy finite state machine (Required Improvements 3).

States and legal transitions:

    IDLE                 -> AWAITING_MSS          (CRT trigger)
    AWAITING_MSS         -> AWAITING_RETRACEMENT  (MSS confirmed, OB valid)
    AWAITING_MSS         -> IDLE                  (MSS invalidated / setup discarded)
    AWAITING_RETRACEMENT -> ACTIVE_TRADE          (entry filled)
    AWAITING_RETRACEMENT -> IDLE                  (pending order expired)
    ACTIVE_TRADE         -> CLOSED                (target or stop)
    CLOSED               -> IDLE                  (statistics recorded)

Any other transition raises — hidden logic errors fail loudly instead of
corrupting the simulation.
"""

from enum import Enum


class State(Enum):
    IDLE = "idle"
    AWAITING_MSS = "awaiting_mss"
    AWAITING_RETRACEMENT = "awaiting_retracement"
    ACTIVE_TRADE = "active_trade"
    CLOSED = "closed"


_ALLOWED = {
    State.IDLE: {State.AWAITING_MSS},
    State.AWAITING_MSS: {State.AWAITING_RETRACEMENT, State.IDLE},
    State.AWAITING_RETRACEMENT: {State.ACTIVE_TRADE, State.IDLE},
    State.ACTIVE_TRADE: {State.CLOSED},
    State.CLOSED: {State.IDLE},
}


class InvalidTransition(RuntimeError):
    pass


class StateMachine:
    def __init__(self):
        self.state = State.IDLE
        self.history: list[tuple[object, State]] = []

    def to(self, new_state: State, timestamp=None) -> None:
        if new_state not in _ALLOWED[self.state]:
            raise InvalidTransition(f"{self.state.value} -> {new_state.value}")
        self.state = new_state
        self.history.append((timestamp, new_state))

    @property
    def is_idle(self) -> bool:
        return self.state is State.IDLE
