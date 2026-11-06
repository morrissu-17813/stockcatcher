from __future__ import annotations

import json
from pathlib import Path

import pytest

from tianji_3k.validation.strategy_intelligence import (
    build_intelligence_report,
    write_intelligence_reports,
)


def test_unknown_close_is_not_counted_as_loss_and_proxy_is_separate():
    rows = [
        {"record_source": "prediction_ledger", "prediction_id": "p1",
         "close_return_pct": 2.0, "mfe_pct": 3.0, "mae_pct": -0.5,
         "confidence": 90, "projected_volume_ratio": 2.5,
         "signal_time": "2026-11-06T10:00:00+08:00", "signal_level": "STRONG"},
        {"record_source": "prediction_ledger", "prediction_id": "p2",
         "close_return_pct": -1.0, "mfe_pct": 0.5, "mae_pct": -2.0,
         "confidence": 70, "projected_volume_ratio": 1.2,
         "signal_time": "2026-11-06T11:00:00+08:00", "signal_level": "MOMENTUM"},
        {"record_source": "prediction_ledger", "prediction_id": "p3",
         "close_return_pct": None, "mfe_pct": None, "mae_pct": None},
        {"record_source": "historical_xlsx", "proxy_return_pct": 8.0,
         "close_return_pct": None},
    ]
    report = build_intelligence_report(rows)
    assert report["record_counts"]["prediction_ledger_events"] == 3
    assert report["record_counts"]["verified_close_outcomes"] == 2
    assert report["record_counts"]["ledger_outcomes_unknown"] == 1
    assert report["verified_close_performance"]["positive_count"] == 1
    assert report["verified_close_performance"]["negative_count"] == 1
    assert report["verified_close_performance"]["sample_count"] == 2
    assert report["historical_workbook_proxy_separate"]["sample_count"] == 1
    assert report["historical_workbook_proxy_separate"]["mean_pct"] == 8.0
    assert report["verified_close_performance"]["mean_pct"] == 0.5
    assert report["formal_strategy_modified"] is False
    assert report["market_data_api_calls"] == 0


def test_segment_reports_are_descriptive_and_keep_empty_buckets():
    rows = [
        {"record_source": "prediction_ledger", "close_return_pct": 1.5,
         "confidence": 95, "projected_volume_ratio": 2.8,
         "signal_time": "2026-11-06T09:30:00+08:00", "signal_level": "STRONG"},
    ]
    report = build_intelligence_report(rows)
    score = {r["group"]: r for r in report["segments"]["signal_score"]}
    volume = {r["group"]: r for r in report["segments"]["projected_volume_ratio"]}
    assert score["90-100"]["sample_count"] == 1
    assert volume[">=2.3x"]["sample_count"] == 1
    assert "No segment is promoted" in report["interpretation_guardrails"][4]


def test_report_outputs_are_complete_and_refuse_overwrite(tmp_path: Path):
    report = build_intelligence_report([
        {"record_source": "prediction_ledger", "close_return_pct": 0.5}
    ])
    out = tmp_path / "report"
    paths = write_intelligence_reports(report, out)
    assert set(paths) == {"json", "csv", "markdown", "html"}
    assert all(Path(p).exists() for p in paths.values())
    with pytest.raises(FileExistsError):
        write_intelligence_reports(report, out)
