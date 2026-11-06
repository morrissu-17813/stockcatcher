import json
from pathlib import Path

from tianji_3k.validation.shadow_validation import run_shadow_validation


def _write_jsonl(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def test_shadow_validation_is_read_only_and_labels_missing_as_unknown(tmp_path):
    predictions = tmp_path / "predictions"
    validation = tmp_path / "validation"
    out = tmp_path / "reports"
    pred = {
        "prediction_id": "p1", "trade_date": "2026-10-20", "symbol": "5340",
        "event_type": "INTRADAY_3K_PREDICTION", "created_at": "2026-10-20T09:00:00+08:00",
        "context": {"trade_date": "2026-10-20", "symbol": "5340", "name": "test", "stage0_pass": True},
        "trigger_snapshot": {"observed_at": "2026-10-20T09:00:00+08:00", "current_price": 100, "breakout_level": 99},
        "volume_snapshot": {"projected_ratio": 2.0},
    }
    events = [pred, {"event_type": "POST_SIGNAL_PRICE_SAMPLE", "prediction_id": "p1", "sample_type": "T_PLUS_5M", "status": "OBSERVED", "return_pct": 1.5},
              {"event_type": "POST_SIGNAL_TRACKING_FINAL", "prediction_id": "p1", "ground_truth_available": False, "close_return_pct": None, "mfe_pct": 2, "mae_pct": -1}]
    _write_jsonl(predictions / "2026-10-20" / "5340" / "events.jsonl", events)
    _write_jsonl(validation / "master_prediction_log.jsonl", [pred])
    source_before = (predictions / "2026-10-20" / "5340" / "events.jsonl").read_bytes()

    summary = run_shadow_validation(predictions, validation, out)

    rows = json.loads((out / "shadow_validation_dataset.json").read_text(encoding="utf-8"))
    assert summary["formal_strategy_modified"] is False
    assert summary["api_calls_made"] == 0
    assert summary["telegram_messages_sent"] == 0
    assert summary["prediction_ledger_records"] == 1
    assert rows[0]["t_plus_5m_status"] == "OBSERVED"
    assert rows[0]["t_plus_15m_status"] == "UNKNOWN"
    assert rows[0]["ground_truth_available"] is False
    assert (predictions / "2026-10-20" / "5340" / "events.jsonl").read_bytes() == source_before


def test_shadow_validation_deduplicates_master_and_symbol_ledger(tmp_path):
    predictions = tmp_path / "predictions"
    validation = tmp_path / "validation"
    pred = {"prediction_id": "p1", "trade_date": "2026-10-20", "symbol": "5340", "event_type": "INTRADAY_3K_PREDICTION", "context": {}, "trigger_snapshot": {}, "volume_snapshot": {}}
    _write_jsonl(predictions / "2026-10-20" / "5340" / "events.jsonl", [pred])
    _write_jsonl(validation / "master_prediction_log.jsonl", [pred])
    summary = run_shadow_validation(predictions, validation, tmp_path / "out")
    assert summary["prediction_ledger_records"] == 1
    assert summary["records_total"] == 1


def test_shadow_validation_refuses_to_overwrite_existing_report(tmp_path):
    predictions = tmp_path / "predictions"
    validation = tmp_path / "validation"
    out = tmp_path / "reports"
    out.mkdir()
    marker = out / "keep.txt"
    marker.write_text("previous run", encoding="utf-8")

    import pytest
    with pytest.raises(FileExistsError):
        run_shadow_validation(predictions, validation, out)

    assert marker.read_text(encoding="utf-8") == "previous run"
