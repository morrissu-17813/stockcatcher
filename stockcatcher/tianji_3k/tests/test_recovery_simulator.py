import json
from pathlib import Path

from tianji_3k.core.recovery import RecoveryManager
from tianji_3k.core.simulator import IntradaySimulator
from tianji_3k.core.state_machine import IntradayStateMachine


def snap(t, price, identity, up=None):
    return {
        "symbol": "2221", "observed_at": f"2026-09-23T{t}+08:00",
        "current_price": price, "previous_close": 100, "today_open": 100,
        "cumulative_volume": 500000, "up_pct": (price/100-1)*100 if up is None else up,
        "is_traded": True, "data_identity": identity,
    }


def test_simulator_trigger_and_rearm():
    rows = [snap("09:10:00", 104, "a"), snap("09:10:20", 105, "b"),
            snap("09:10:40", 103, "c"), snap("09:11:00", 104, "d"),
            snap("09:11:20", 105, "e")]
    r = IntradaySimulator({"2221": 100}, 0.3).run(rows)
    assert r.triggers == 2


def test_simulator_duplicate_identity_does_not_confirm():
    rows = [snap("09:10:00", 104, "same"), snap("09:10:20", 105, "same"), snap("09:10:40", 105, "new")]
    r = IntradaySimulator({"2221": 100}, 0.3).run(rows)
    assert r.triggers == 1
    assert r.reasons["DUPLICATE_SNAPSHOT"] == 1


def test_recovery_checkpoint_detects_unclean_state(tmp_path):
    p = tmp_path / "runtime_checkpoint.json"
    rm = RecoveryManager(p)
    rm.start("2026-09-23", "RUNNING")
    data = json.loads(p.read_text())
    assert data["clean_shutdown"] is False
    assert data["trade_date"] == "2026-09-23"
    rm.mark_clean_shutdown()
    assert rm.recovery_needed() is False


def test_state_machine_persists_seen_identities():
    sm = IntradayStateMachine()
    rows = [snap("09:10:00", 104, "a"), snap("09:10:20", 105, "b")]
    for raw in rows:
        from tianji_3k.core.snapshot import build_snapshot
        sm.evaluate(build_snapshot("2221", raw), 100)
    restored = IntradayStateMachine.from_dict(sm.to_dict())
    assert restored.seen_data_identities == {"a", "b"}
    assert restored.trigger_count == sm.trigger_count
