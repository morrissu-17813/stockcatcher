import json
from pathlib import Path

from tianji_3k.validation.prediction_ledger import PredictionLedger
from tianji_3k.validation.daily_report import build_daily_report


def test_prediction_is_append_only(tmp_path):
    ledger = PredictionLedger(tmp_path / "predictions")
    ctx = {"trade_date": "2026-09-23", "symbol": "1234"}
    e = ledger.create_prediction(ctx, {"observed_at": "2026-09-23T09:10:00+08:00"}, {"projected_ratio": 1.7}, {"status": "READY"})
    ledger.append_event("2026-09-23", "1234", {"event_type": "NOTIFICATION", "prediction_id": e["prediction_id"], "notification_status": "SENT"})
    lines = (tmp_path / "predictions" / "2026-09-23" / "1234" / "events.jsonl").read_text().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["immutable"] is True
    assert json.loads(lines[0])["notification_status"] == "READY"
    assert json.loads(lines[1])["notification_status"] == "SENT"


def test_daily_report_counts_prediction_validation():
    report = build_daily_report(
        "2026-09-23", [{"symbol": "1234"}],
        [{"event_type": "INTRADAY_3K_PREDICTION", "notification_status": "READY"}],
        [{"symbol": "1234", "ground_truth_3k": True}],
        [{"prediction_id": "p1", "symbol": "1234", "ground_truth_3k": True}],
    )
    assert report["prediction_count"] == 1
    assert report["validated_prediction_count"] == 1
    assert report["ground_truth_hit_count"] == 1
    assert report["hit_rate"] == 1.0

def test_prediction_lookup_and_validation_idempotence(tmp_path):
    ledger = PredictionLedger(tmp_path / "predictions")
    ctx = {"trade_date": "2026-09-23", "symbol": "2221"}
    e = ledger.create_prediction(ctx, {"snapshot_id": "snap-1", "observed_at": "2026-09-23T09:10:00+08:00"}, {}, {"status": "READY"})
    assert ledger.find_prediction_by_snapshot("2026-09-23", "2221", "snap-1")["prediction_id"] == e["prediction_id"]
    ledger.append_event("2026-09-23", "2221", {"event_type": "PREDICTION_VALIDATION", "prediction_id": e["prediction_id"]})
    assert ledger.has_event("2026-09-23", "2221", "PREDICTION_VALIDATION", "prediction_id", e["prediction_id"])
