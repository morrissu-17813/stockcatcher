from tianji_3k.strategy.three_k import evaluate_three_k


def test_evaluate_three_k_high_score_triggers():
    snapshot = {"symbol": "TEST"}

    direction = {
        "week_kd_golden_cross": True,
        "day_kd_up": True,
    }

    breakout = {
        "breakout": True,
        "volume_ratio": 2.0,
        "gain_pct": 5.0,
    }

    result = evaluate_three_k(snapshot, direction, breakout)

    assert result["status"] == "TRIGGER"
    assert result["score"] == 100
    assert result["reason"]


def test_evaluate_three_k_watch():
    snapshot = {"symbol": "TEST"}

    direction = {
        "week_kd_golden_cross": True,
        "day_kd_up": True,
    }

    breakout = {
        "breakout": False,
        "volume_ratio": 1.0,
        "gain_pct": 2.0,
    }

    result = evaluate_three_k(snapshot, direction, breakout)

    # 25 + 20 = 45 -> WATCH
    assert result["status"] == "WATCH"
    assert result["score"] == 45
    assert result["reason"]


def test_evaluate_three_k_reject():
    snapshot = {"symbol": "TEST"}

    direction = {
        "week_kd_golden_cross": False,
        "day_kd_up": False,
    }

    breakout = {
        "breakout": False,
        "volume_ratio": 1.0,
        "gain_pct": 1.0,
    }

    result = evaluate_three_k(snapshot, direction, breakout)

    assert result["status"] == "REJECT"
    assert result["score"] == 0
    assert result["reason"]


def test_evaluate_three_k_volume_and_gain_components():
    snapshot = {"symbol": "TEST"}

    direction = {
        "week_kd_golden_cross": True,
        "day_kd_up": False,
    }

    breakout = {
        "breakout": False,
        "volume_ratio": 1.5,
        "gain_pct": 4.0,
    }

    result = evaluate_three_k(snapshot, direction, breakout)

    # 25 + 15 + 10 = 50 -> WATCH
    assert result["status"] == "WATCH"
    assert result["score"] == 50
    assert result["reason"]
