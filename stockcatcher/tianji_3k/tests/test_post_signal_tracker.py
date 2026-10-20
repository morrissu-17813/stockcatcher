from datetime import datetime, timedelta, timezone
from pathlib import Path

from tianji_3k.validation.prediction_ledger import PredictionLedger
from tianji_3k.validation.post_signal_tracker import PostSignalTracker

TZ = timezone(timedelta(hours=8))
TD = "2026-10-20"


def snapshot(symbol, price, at, identity):
    return {
        "symbol": symbol,
        "current_price": price,
        "observed_at": at.isoformat(),
        "snapshot_id": identity,
        "data_identity": identity,
    }


def prediction(ledger, symbol="5340", entry=100.0, at=None):
    at = at or datetime(2026, 10, 20, 9, 0, tzinfo=TZ)
    return ledger.create_prediction(
        {"trade_date": TD, "symbol": symbol, "name": "test"},
        {"observed_at": at.isoformat(), "current_price": entry, "snapshot_id": "entry-snap"},
        {"projected_ratio": 2.0},
        {"should_send": True, "status": "READY"},
    )


def test_tracker_persists_milestones_and_extrema(tmp_path):
    ledger = PredictionLedger(tmp_path / "predictions")
    p = prediction(ledger)
    tracker = PostSignalTracker(tmp_path / "predictions", ledger)

    assert tracker.observe(TD, {"5340": snapshot("5340", 102, datetime(2026, 10, 20, 9, 4, tzinfo=TZ), "s1")}) >= 1
    tracker.observe(TD, {"5340": snapshot("5340", 105, datetime(2026, 10, 20, 9, 5, tzinfo=TZ), "s2")})
    tracker.observe(TD, {"5340": snapshot("5340", 98, datetime(2026, 10, 20, 9, 15, tzinfo=TZ), "s3")})
    tracker.observe(TD, {"5340": snapshot("5340", 101, datetime(2026, 10, 20, 9, 30, tzinfo=TZ), "s4")})

    events = ledger.events_for_symbol(TD, "5340")
    samples = [e for e in events if e.get("event_type") == "POST_SIGNAL_PRICE_SAMPLE"]
    assert [e["sample_type"] for e in samples] == ["T_PLUS_5M", "T_PLUS_15M", "T_PLUS_30M"]
    assert samples[0]["return_pct"] == 5.0
    assert samples[1]["return_pct"] == -2.0
    state = (tmp_path / "predictions" / TD / "post_signal_tracking.json").read_text()
    assert p["prediction_id"] in state


def test_tracker_restart_restores_extrema_and_deduplicates_snapshot(tmp_path):
    ledger = PredictionLedger(tmp_path / "predictions")
    prediction(ledger)
    tracker = PostSignalTracker(tmp_path / "predictions", ledger)
    snap = snapshot("5340", 106, datetime(2026, 10, 20, 9, 3, tzinfo=TZ), "same")
    tracker.observe(TD, {"5340": snap})

    restarted = PostSignalTracker(tmp_path / "predictions", ledger)
    restarted.observe(TD, {"5340": snap})
    restarted.observe(TD, {"5340": snapshot("5340", 99, datetime(2026, 10, 20, 9, 4, tzinfo=TZ), "next")})

    import json
    state = json.loads((tmp_path / "predictions" / TD / "post_signal_tracking.json").read_text())
    item = next(iter(state.values()))
    assert item["max_price"] == 106
    assert item["min_price"] == 99
    assert item["mfe_pct"] == 6.0
    assert item["mae_pct"] == -1.0
    samples = [e for e in ledger.events_for_symbol(TD, "5340") if e.get("event_type") == "POST_SIGNAL_PRICE_SAMPLE"]
    assert samples == []


def test_close_finalization_is_per_prediction_and_idempotent(tmp_path):
    ledger = PredictionLedger(tmp_path / "predictions")
    p1 = prediction(ledger, at=datetime(2026, 10, 20, 9, 0, tzinfo=TZ))
    p2 = prediction(ledger, at=datetime(2026, 10, 20, 9, 1, tzinfo=TZ))
    tracker = PostSignalTracker(tmp_path / "predictions", ledger)
    tracker.observe(TD, {"5340": snapshot("5340", 103, datetime(2026, 10, 20, 9, 3, tzinfo=TZ), "s1")})
    gt = {"5340": {"trade_date": TD, "symbol": "5340", "close": 104, "ground_truth_3k": True}}

    assert tracker.finalize_close(TD, gt) == 2
    assert tracker.finalize_close(TD, gt) == 0
    events = ledger.events_for_symbol(TD, "5340")
    finals = [e for e in events if e.get("event_type") == "POST_SIGNAL_TRACKING_FINAL"]
    assert {e["prediction_id"] for e in finals} == {p1["prediction_id"], p2["prediction_id"]}
    assert all(e["ground_truth_available"] for e in finals)
    assert all(e["close_return_pct"] is not None for e in finals)


def test_close_finalization_marks_missing_ground_truth_and_milestones(tmp_path):
    ledger = PredictionLedger(tmp_path / "predictions")
    prediction(ledger)
    tracker = PostSignalTracker(tmp_path / "predictions", ledger)
    assert tracker.finalize_close(TD, {}) == 1
    final = next(e for e in ledger.events_for_symbol(TD, "5340") if e.get("event_type") == "POST_SIGNAL_TRACKING_FINAL")
    assert final["ground_truth_available"] is False
    assert final["close_price"] is None
    assert final["missing_milestones"] == ["T_PLUS_5M", "T_PLUS_15M", "T_PLUS_30M"]


def test_tracker_marks_late_milestone_as_missing_instead_of_mislabeling_price(tmp_path):
    ledger = PredictionLedger(tmp_path / "predictions")
    prediction(ledger)
    tracker = PostSignalTracker(tmp_path / "predictions", ledger)
    tracker.observe(TD, {"5340": snapshot("5340", 104, datetime(2026, 10, 20, 9, 20, tzinfo=TZ), "late")})
    events = ledger.events_for_symbol(TD, "5340")
    t5 = next(e for e in events if e.get("event_type") == "POST_SIGNAL_PRICE_SAMPLE" and e.get("sample_type") == "T_PLUS_5M")
    assert t5["status"] == "MISSED_WINDOW"
    assert "sample_price" not in t5


def test_report_is_one_row_per_prediction(tmp_path):
    ledger = PredictionLedger(tmp_path / "predictions")
    p1 = prediction(ledger)
    p2 = prediction(ledger, at=datetime(2026, 10, 20, 9, 1, tzinfo=TZ))
    tracker = PostSignalTracker(tmp_path / "predictions", ledger)
    tracker.finalize_close(TD, {"5340": {"close": 101, "ground_truth_3k": False}})
    paths = tracker.write_report(TD)
    import csv
    with open(paths["csv"], encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 2
    assert {r["prediction_id"] for r in rows} == {p1["prediction_id"], p2["prediction_id"]}
    assert rows[0]["ground_truth_available"] == "True"


def test_tracker_recovers_ledger_sample_if_state_save_was_interrupted(tmp_path):
    ledger = PredictionLedger(tmp_path / "predictions")
    p = prediction(ledger)
    tracker = PostSignalTracker(tmp_path / "predictions", ledger)
    tracker.observe(TD, {"5340": snapshot("5340", 101, datetime(2026, 10, 20, 9, 5, tzinfo=TZ), "milestone")})

    # Simulate a crash window: durable event exists, but milestone was lost from state.
    import json
    state_path = tmp_path / "predictions" / TD / "post_signal_tracking.json"
    state = json.loads(state_path.read_text())
    state[p["prediction_id"]]["milestones"] = {}
    state_path.write_text(json.dumps(state))

    restarted = PostSignalTracker(tmp_path / "predictions", ledger)
    restarted.observe(TD, {"5340": snapshot("5340", 101, datetime(2026, 10, 20, 9, 5, tzinfo=TZ), "milestone")})
    samples = [e for e in ledger.events_for_symbol(TD, "5340") if e.get("event_type") == "POST_SIGNAL_PRICE_SAMPLE"]
    assert len(samples) == 1
