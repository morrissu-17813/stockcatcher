from tianji_3k.core.engine import Tianji3KEngine


def test_trigger():
    snapshot = {
        "symbol": "TEST",
        "close": 105,
        "volume": 2000,
        "prev_close": 100,
        "prev_volume": 1000,
        "high": 106,
        "prev_high": 103,
        "prev2_high": 104,
        "week_kd_golden_cross": True,
        "day_kd_up": True,
    }
    result = Tianji3KEngine().run(snapshot)
    assert result.status == "TRIGGER"
    assert result.score >= 70
