from tianji_3k.core.snapshot import build_snapshot
from tianji_3k.core.state_machine import IntradayStateMachine
from tianji_3k.data.snapshot_filter import SnapshotUniverseFilter
from tianji_3k.notification.gate import evaluate_intraday_notification

def raw(identity,up=4.3):
    return {"observed_at":"2026-09-22T09:10:20+08:00","current_price":121.0,"previous_close":116.0,"today_open":116.5,"cumulative_volume":2000000,"up_pct":up,"is_traded":True,"data_identity":identity}

def test_filter():
    f=SnapshotUniverseFilter()
    assert not f.evaluate({"symbol":"0050","product_type":"ETF","yesterday_volume_lots":10000}).eligible
    assert f.evaluate({"symbol":"2221","product_type":"COMMON_STOCK","yesterday_volume_lots":501}).eligible

def test_financial_kept():
    assert SnapshotUniverseFilter().evaluate({"symbol":"2881","product_type":"COMMON_STOCK","yesterday_volume_lots":800,"is_financial":True}).eligible

def test_duplicate():
    sm=IntradayStateMachine(); s=build_snapshot("2221",raw("same"))
    assert not sm.evaluate(s,120)[0]
    assert sm.evaluate(s,120)[1]=="DUPLICATE_SNAPSHOT"

def test_two_distinct():
    sm=IntradayStateMachine()
    assert not sm.evaluate(build_snapshot("2221",raw("a")),120)[0]
    assert sm.evaluate(build_snapshot("2221",raw("b")),120)[0]

def test_momentum_gate_is_not_suppressed():
    assert evaluate_intraday_notification(9.49).should_send
    d=evaluate_intraday_notification(9.50)
    assert d.should_send and d.status == "MOMENTUM"

def test_trigger_requires_invalidation_before_rearm():
    sm = IntradayStateMachine()
    assert not sm.evaluate(build_snapshot("2221", raw("a")), 120)[0]
    assert sm.evaluate(build_snapshot("2221", raw("b")), 120)[0]
    assert not sm.evaluate(build_snapshot("2221", raw("c")), 120)[0]
    assert sm.state.value == "TRIGGERED"
    # A non-valid snapshot invalidates the prior trigger.
    bad = raw("d", up=3.0)
    assert not sm.evaluate(build_snapshot("2221", bad), 120)[0]
    assert sm.state.value == "INVALIDATED"
    # Fresh breakout needs two new distinct valid snapshots.
    assert not sm.evaluate(build_snapshot("2221", raw("e")), 120)[0]
    assert sm.evaluate(build_snapshot("2221", raw("f")), 120)[0]


def test_build_snapshot_accepts_explicit_mis_lots():
    s = build_snapshot("2221", {"observed_at":"2026-09-22T09:10:20+08:00", "current_price":121, "previous_close":116, "today_open":116.5, "cumulative_volume_lots":2000, "up_pct":4.3, "is_traded":True, "data_identity":"x"})
    assert s.cumulative_volume_lots == 2000
