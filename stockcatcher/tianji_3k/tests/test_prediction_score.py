from tianji_3k.core.prediction_score import IntradayPredictionScorer


def ctx():
    return {"ma20": 120, "ma60": 110, "ma20_prev": 119, "previous_close": 116, "breakout_level": 120}


def test_score_is_explainable_and_not_probability():
    s = IntradayPredictionScorer().score(
        context=ctx(), current_price=121, up_pct=4.31,
        projected_ratio=2.0, effective_breakout=True, confirmed_snapshots=2,
    )
    assert s.total == 100
    assert s.trend == 30
    assert s.breakout == 30
    assert s.volume == 30
    assert s.price == 10
    assert s.to_dict()["components"]["volume"]["threshold_ratio"] == 1.5


def test_score_degrades_with_weak_volume():
    s = IntradayPredictionScorer().score(
        context=ctx(), current_price=121, up_pct=4.31,
        projected_ratio=1.5, effective_breakout=True, confirmed_snapshots=2,
    )
    assert 80 <= s.total < 100
    assert s.volume == 15
