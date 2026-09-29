from datetime import datetime, timezone
from tianji_3k.core.volume_predictor import IntradayVolumePredictor


def test_volume_projection_not_ready_before_five_minutes():
    p = IntradayVolumePredictor()
    r = p.project(1000, datetime(2026, 9, 22, 9, 2, tzinfo=timezone.utc), 1000)
    assert not r.ready
    assert r.projected_ratio is None


def test_volume_projection_ready_after_five_minutes():
    p = IntradayVolumePredictor()
    r = p.project(1000, datetime(2026, 9, 22, 9, 10, tzinfo=timezone.utc), 1000)
    assert r.ready
    assert r.projected_volume_lots == 27000
    assert r.projected_ratio == 27
