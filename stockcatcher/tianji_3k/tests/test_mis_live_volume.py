from datetime import datetime, timedelta, timezone

from tianji_3k.core.mis_live_volume import MISLiveVolumeEstimator

TAIPEI = timezone(timedelta(hours=8))


def test_estimator_uses_only_local_snapshots_and_daily_vma_baseline():
    estimator = MISLiveVolumeEstimator()
    base = datetime(2026, 10, 12, 10, 0, tzinfo=TAIPEI)
    first = estimator.observe("2330", base, 1000, 5400)
    second = estimator.observe("2330", base + timedelta(seconds=30), 1030, 5400)
    third = estimator.observe("2330", base + timedelta(seconds=60), 1080, 5400)
    assert first["ready"] is False
    assert second["ready"] is False
    assert third["ready"] is True
    assert third["pass"] is True
    assert third["baseline_source"] == "VMA5_DAILY_DIV_54"
    assert third["volume_delta_lots"] == 80.0
    assert third["live_volume_ratio"] > 1.5


def test_estimator_rejects_low_volume_pace():
    estimator = MISLiveVolumeEstimator()
    base = datetime(2026, 10, 12, 11, 0, tzinfo=TAIPEI)
    estimator.observe("2317", base, 1000, 5400)
    estimator.observe("2317", base + timedelta(seconds=30), 1002, 5400)
    result = estimator.observe("2317", base + timedelta(seconds=60), 1003, 5400)
    assert result["ready"] is True
    assert result["pass"] is False
    assert result["reason"] == "VOLUME_PACE_BELOW_THRESHOLD"


def test_estimator_resets_after_cumulative_volume_rollback():
    estimator = MISLiveVolumeEstimator()
    base = datetime(2026, 10, 12, 11, 0, tzinfo=TAIPEI)
    estimator.observe("2603", base, 1000, 5400)
    estimator.observe("2603", base + timedelta(seconds=30), 1010, 5400)
    result = estimator.observe("2603", base + timedelta(seconds=60), 900, 5400)
    assert result["ready"] is False
    assert result["reason"] == "INSUFFICIENT_WINDOW"


def test_estimator_retains_150_second_radar_gap_and_normalizes_by_actual_time():
    estimator = MISLiveVolumeEstimator()
    base = datetime(2026, 10, 12, 10, 0, tzinfo=TAIPEI)
    first = estimator.observe("2609", base, 1000, 5400)
    second = estimator.observe("2609", base + timedelta(seconds=150), 1100, 5400)
    assert first["ready"] is False
    assert second["ready"] is True
    assert second["pass"] is True
    assert second["window_seconds"] == 150.0
    assert second["expected_volume_lots"] == 50.0
    assert second["live_volume_ratio"] == 2.0
    assert second["max_window_seconds"] == 240.0


def test_estimator_resets_after_gap_exceeds_240_seconds():
    estimator = MISLiveVolumeEstimator()
    base = datetime(2026, 10, 12, 10, 0, tzinfo=TAIPEI)
    estimator.observe("2610", base, 1000, 5400)
    result = estimator.observe("2610", base + timedelta(seconds=241), 1200, 5400)
    assert result["ready"] is False
    assert result["reason"] == "INSUFFICIENT_WINDOW"
    assert result["max_window_seconds"] == 240.0
