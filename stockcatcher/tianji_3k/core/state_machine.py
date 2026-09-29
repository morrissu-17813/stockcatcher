from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class RadarState(str, Enum):
    WATCHING = "WATCHING"
    BREAKOUT_PENDING = "BREAKOUT_PENDING"
    TRIGGERED = "TRIGGERED"
    INVALIDATED = "INVALIDATED"
    COOLDOWN = "COOLDOWN"
    REARMED = "REARMED"


@dataclass
class IntradayStateMachine:
    """Per-symbol intraday state machine.

    A trigger requires two consecutive *distinct* data identities while all
    price conditions remain valid. After a trigger, the machine cannot trigger
    again until the breakout is invalidated and a fresh breakout sequence starts.
    """

    state: RadarState = RadarState.WATCHING
    last_snapshot_id: str = ""
    last_data_identity: str = ""
    pending_count: int = 0
    trigger_count: int = 0
    last_trigger_price: float = 0.0
    seen_data_identities: set[str] = field(default_factory=set)

    def evaluate(self, snapshot, breakout_level: float, gain_threshold_pct: float = 4.0,
                 breakout_buffer_pct: float = 0.3):
        identity = snapshot.data_identity or snapshot.payload_hash
        snapshot_id = snapshot.snapshot_id

        if snapshot_id == self.last_snapshot_id or identity in self.seen_data_identities:
            return False, "DUPLICATE_SNAPSHOT"
        self.last_snapshot_id = snapshot_id
        self.last_data_identity = identity
        self.seen_data_identities.add(identity)

        effective = snapshot.current_price >= breakout_level * (1 + breakout_buffer_pct / 100)
        price_ok = (
            snapshot.is_traded
            and snapshot.previous_close > 0
            and snapshot.today_open > 0
            and snapshot.current_price > snapshot.today_open
            and snapshot.up_pct >= gain_threshold_pct
            and snapshot.current_price / snapshot.previous_close - 1 >= gain_threshold_pct / 100
        )
        valid = bool(effective and price_ok)

        # A previous trigger must first be invalidated before another trigger
        # can be armed. This prevents repeated notifications every two polls.
        if self.state == RadarState.TRIGGERED:
            if not valid:
                self.state = RadarState.INVALIDATED
                self.pending_count = 0
                return False, "TRIGGER_INVALIDATED"
            return False, "ALREADY_TRIGGERED_WAIT_REARM"

        if self.state == RadarState.COOLDOWN:
            if not valid:
                return False, "COOLDOWN"
            self.state = RadarState.REARMED
            self.pending_count = 0

        if valid:
            if self.state in {RadarState.INVALIDATED, RadarState.REARMED, RadarState.WATCHING}:
                self.state = RadarState.BREAKOUT_PENDING
            self.pending_count += 1
            if self.pending_count >= 2:
                self.pending_count = 0
                self.trigger_count += 1
                self.last_trigger_price = snapshot.current_price
                self.state = RadarState.TRIGGERED
                return True, "EFFECTIVE_BREAKOUT"
            return False, "FIRST_VALID_CONFIRMATION"

        self.pending_count = 0
        if self.state == RadarState.BREAKOUT_PENDING:
            self.state = RadarState.INVALIDATED
            return False, "BREAKOUT_INVALIDATED"
        if self.state == RadarState.INVALIDATED:
            self.state = RadarState.COOLDOWN
            return False, "COOLDOWN"
        if self.state == RadarState.REARMED:
            self.state = RadarState.WATCHING
            return False, "REARM_CANCELLED"
        self.state = RadarState.WATCHING
        return False, "BREAKOUT_CONDITIONS_NOT_MET"

    def to_dict(self) -> dict:
        return {
            "schema_version": "state-v1",
            "state": self.state.value,
            "last_snapshot_id": self.last_snapshot_id,
            "last_data_identity": self.last_data_identity,
            "pending_count": self.pending_count,
            "trigger_count": self.trigger_count,
            "last_trigger_price": self.last_trigger_price,
            "seen_data_identities": sorted(self.seen_data_identities),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "IntradayStateMachine":
        obj = cls()
        obj.state = RadarState(data.get("state", RadarState.WATCHING.value))
        obj.last_snapshot_id = str(data.get("last_snapshot_id", ""))
        obj.last_data_identity = str(data.get("last_data_identity", ""))
        obj.pending_count = int(data.get("pending_count", 0))
        obj.trigger_count = int(data.get("trigger_count", 0))
        obj.last_trigger_price = float(data.get("last_trigger_price", 0) or 0)
        obj.seen_data_identities = set(str(x) for x in data.get("seen_data_identities", []) if x)
        return obj
