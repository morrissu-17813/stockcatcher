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


def test_prediction_schema_v22_has_normalized_signal_and_hash(tmp_path):
    ledger = PredictionLedger(tmp_path / "predictions")
    ctx = {
        "trade_date": "2026-09-23", "symbol": "1234", "breakout_level": 98.5,
        "stage0_pass": True, "stage1_pass": True, "stage2_pass": True,
        "stage3_pass": True, "final_pool": True,
    }
    trigger = {
        "snapshot_id": "snap-v22", "observed_at": "2026-09-23T09:10:00+08:00",
        "current_price": 101.0, "up_pct": 4.2, "signal_level": "STRONG",
        "prediction_score": 88,
    }
    volume = {"projected_ratio": 2.3, "live_volume_ratio": 1.8, "vma5_lots": 1200}
    event = ledger.create_prediction(ctx, trigger, volume, {"status": "READY"})
    assert event["schema_version"] == "prediction-v2.2"
    assert event["signal"]["signal_price"] == 101.0
    assert event["signal"]["breakout_base"] == 98.5
    assert event["signal"]["projected_volume_ratio"] == 2.3
    assert event["source"]["signal_origin"] == "FORMAL_3K"
    assert len(event["record_hash"]) == 64
    assert ledger.audit("2026-09-23")["integrity_ok"] is True


def test_prediction_create_is_idempotent_for_same_snapshot_and_time(tmp_path):
    ledger = PredictionLedger(tmp_path / "predictions")
    ctx = {"trade_date": "2026-09-23", "symbol": "1234"}
    trigger = {"snapshot_id": "snap-1", "observed_at": "2026-09-23T09:10:00+08:00"}
    first = ledger.create_prediction(ctx, trigger, {}, {"status": "READY"})
    second = ledger.create_prediction(ctx, trigger, {}, {"status": "READY"})
    assert first["prediction_id"] == second["prediction_id"]
    assert len(list(ledger.iter_predictions("2026-09-23"))) == 1


def test_master_prediction_log_can_be_rebuilt_from_canonical_events(tmp_path):
    ledger = PredictionLedger(tmp_path / "predictions")
    ctx = {"trade_date": "2026-09-23", "symbol": "1234"}
    event = ledger.create_prediction(ctx, {"snapshot_id": "snap-1"}, {}, {"status": "READY"})
    master = ledger.validation_root / "master_prediction_log.jsonl"
    master.write_text("", encoding="utf-8")
    audit = ledger.audit("2026-09-23")
    assert event["prediction_id"] in audit["master_missing_prediction_ids"]
    result = ledger.rebuild_master_prediction_log()
    assert result["rebuilt_count"] == 1
    assert ledger.audit("2026-09-23")["integrity_ok"] is True
