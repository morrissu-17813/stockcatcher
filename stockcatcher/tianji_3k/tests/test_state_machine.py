from dataclasses import dataclass

from tianji_3k.core.state_machine import IntradayStateMachine, RadarState


@dataclass
class Snapshot:
    snapshot_id: str
    data_identity: str
    current_price: float
    previous_close: float = 100.0
    today_open: float = 101.0
    up_pct: float = 6.0
    is_traded: bool = True
    payload_hash: str = ""


def snap(
    i: int,
    price: float = 106.0,
    up_pct: float = 6.0,
    identity: str | None = None,
    is_traded: bool = True,
):
    identity = identity or f"data-{i}"
    return Snapshot(
        snapshot_id=f"snapshot-{i}",
        data_identity=identity,
        current_price=price,
        up_pct=up_pct,
        is_traded=is_traded,
        payload_hash=f"payload-{i}",
    )


BREAKOUT_LEVEL = 105.0


def test_first_valid_snapshot_enters_breakout_pending():
    sm = IntradayStateMachine()

    triggered, reason = sm.evaluate(
        snap(1),
        breakout_level=BREAKOUT_LEVEL,
    )

    assert triggered is False
    assert reason == "FIRST_VALID_CONFIRMATION"
    assert sm.state == RadarState.BREAKOUT_PENDING
    assert sm.pending_count == 1
    assert sm.trigger_count == 0


def test_two_distinct_snapshots_trigger_effective_breakout():
    sm = IntradayStateMachine()

    triggered1, reason1 = sm.evaluate(
        snap(1),
        breakout_level=BREAKOUT_LEVEL,
    )

    triggered2, reason2 = sm.evaluate(
        snap(2),
        breakout_level=BREAKOUT_LEVEL,
    )

    assert triggered1 is False
    assert reason1 == "FIRST_VALID_CONFIRMATION"

    assert triggered2 is True
    assert reason2 == "EFFECTIVE_BREAKOUT"

    assert sm.state == RadarState.TRIGGERED
    assert sm.pending_count == 0
    assert sm.trigger_count == 1
    assert sm.last_trigger_price == 106.0


def test_duplicate_snapshot_does_not_confirm():
    sm = IntradayStateMachine()

    triggered1, reason1 = sm.evaluate(
        snap(1),
        breakout_level=BREAKOUT_LEVEL,
    )

    triggered2, reason2 = sm.evaluate(
        snap(1),
        breakout_level=BREAKOUT_LEVEL,
    )

    assert triggered1 is False
    assert reason1 == "FIRST_VALID_CONFIRMATION"

    assert triggered2 is False
    assert reason2 == "DUPLICATE_SNAPSHOT"

    assert sm.state == RadarState.BREAKOUT_PENDING
    assert sm.pending_count == 1
    assert sm.trigger_count == 0


def test_same_data_identity_does_not_confirm_even_with_new_snapshot_id():
    sm = IntradayStateMachine()

    triggered1, reason1 = sm.evaluate(
        snap(1, identity="same-data"),
        breakout_level=BREAKOUT_LEVEL,
    )

    triggered2, reason2 = sm.evaluate(
        snap(2, identity="same-data"),
        breakout_level=BREAKOUT_LEVEL,
    )

    assert triggered1 is False
    assert reason1 == "FIRST_VALID_CONFIRMATION"

    assert triggered2 is False
    assert reason2 == "DUPLICATE_SNAPSHOT"

    assert sm.state == RadarState.BREAKOUT_PENDING
    assert sm.pending_count == 1
    assert sm.trigger_count == 0


def test_triggered_state_does_not_retrigger_on_valid_snapshots():
    sm = IntradayStateMachine()

    sm.evaluate(
        snap(1),
        breakout_level=BREAKOUT_LEVEL,
    )

    triggered, reason = sm.evaluate(
        snap(2),
        breakout_level=BREAKOUT_LEVEL,
    )

    assert triggered is True
    assert reason == "EFFECTIVE_BREAKOUT"
    assert sm.state == RadarState.TRIGGERED
    assert sm.trigger_count == 1

    triggered_again, reason_again = sm.evaluate(
        snap(3),
        breakout_level=BREAKOUT_LEVEL,
    )

    assert triggered_again is False
    assert reason_again == "ALREADY_TRIGGERED_WAIT_REARM"
    assert sm.state == RadarState.TRIGGERED
    assert sm.trigger_count == 1


def test_trigger_is_invalidated_when_conditions_fail():
    sm = IntradayStateMachine()

    sm.evaluate(
        snap(1),
        breakout_level=BREAKOUT_LEVEL,
    )

    triggered, reason = sm.evaluate(
        snap(2),
        breakout_level=BREAKOUT_LEVEL,
    )

    assert triggered is True
    assert reason == "EFFECTIVE_BREAKOUT"
    assert sm.state == RadarState.TRIGGERED

    invalidated, invalidation_reason = sm.evaluate(
        snap(3, price=104.0, up_pct=3.0),
        breakout_level=BREAKOUT_LEVEL,
    )

    assert invalidated is False
    assert invalidation_reason == "TRIGGER_INVALIDATED"
    assert sm.state == RadarState.INVALIDATED
    assert sm.pending_count == 0
    assert sm.trigger_count == 1


def test_invalidated_state_requires_fresh_breakout_sequence():
    sm = IntradayStateMachine()

    sm.evaluate(
        snap(1),
        breakout_level=BREAKOUT_LEVEL,
    )

    sm.evaluate(
        snap(2),
        breakout_level=BREAKOUT_LEVEL,
    )

    invalidated, reason = sm.evaluate(
        snap(3, price=104.0, up_pct=3.0),
        breakout_level=BREAKOUT_LEVEL,
    )

    assert invalidated is False
    assert reason == "TRIGGER_INVALIDATED"
    assert sm.state == RadarState.INVALIDATED

    triggered1, reason1 = sm.evaluate(
        snap(4),
        breakout_level=BREAKOUT_LEVEL,
    )

    assert triggered1 is False
    assert reason1 == "FIRST_VALID_CONFIRMATION"
    assert sm.state == RadarState.BREAKOUT_PENDING
    assert sm.pending_count == 1

    triggered2, reason2 = sm.evaluate(
        snap(5),
        breakout_level=BREAKOUT_LEVEL,
    )

    assert triggered2 is True
    assert reason2 == "EFFECTIVE_BREAKOUT"
    assert sm.state == RadarState.TRIGGERED
    assert sm.trigger_count == 2


def test_breakout_buffer_is_required():
    sm = IntradayStateMachine()

    # breakout_level = 105
    # 0.3% buffer => 105.315
    triggered, reason = sm.evaluate(
        snap(1, price=105.20),
        breakout_level=BREAKOUT_LEVEL,
    )

    assert triggered is False
    assert reason == "BREAKOUT_CONDITIONS_NOT_MET"
    assert sm.state == RadarState.WATCHING
    assert sm.pending_count == 0


def test_price_and_gain_conditions_are_required():
    sm = IntradayStateMachine()

    triggered, reason = sm.evaluate(
        snap(1, price=106.0, up_pct=3.5),
        breakout_level=BREAKOUT_LEVEL,
    )

    assert triggered is False
    assert reason == "BREAKOUT_CONDITIONS_NOT_MET"
    assert sm.state == RadarState.WATCHING
    assert sm.pending_count == 0


def test_state_machine_round_trip_serialization():
    sm = IntradayStateMachine()

    sm.evaluate(
        snap(1),
        breakout_level=BREAKOUT_LEVEL,
    )

    data = sm.to_dict()

    restored = IntradayStateMachine.from_dict(data)

    assert restored.state == sm.state
    assert restored.last_snapshot_id == sm.last_snapshot_id
    assert restored.last_data_identity == sm.last_data_identity
    assert restored.pending_count == sm.pending_count
    assert restored.trigger_count == sm.trigger_count
    assert restored.last_trigger_price == sm.last_trigger_price
    assert restored.seen_data_identities == sm.seen_data_identities
