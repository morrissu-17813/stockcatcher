import json
from pathlib import Path

from tianji_3k.data.daily_refresh import FreshnessResult


def test_freshness_result_roundtrip(tmp_path):
    p = tmp_path / "data_freshness.json"
    result = FreshnessResult("2026-09-23", "2026-09-23", "2026-09-18", "2026-09-23", 10, 9, 1, 9, "OK", "")
    p.write_text(json.dumps(result.__dict__), encoding="utf-8")
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["latest_completed_date"] == "2026-09-23"
    assert data["cache_latest_after"] == "2026-09-23"
    assert data["status"] == "OK"


def test_stale_result_is_not_ok():
    result = FreshnessResult("2026-09-23", "2026-09-23", "2026-09-18", "2026-09-18", 10, 0, 10, 0, "STALE", "cache_latest=2026-09-18, expected=2026-09-23")
    assert result.status != "OK"
    assert result.latest_completed_date != result.cache_latest_after
