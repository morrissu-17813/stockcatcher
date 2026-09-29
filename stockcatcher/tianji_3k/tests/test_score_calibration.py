from tianji_3k.validation.score_calibration import build_calibration_report


def pred(td, sid, score):
    return {
        "trade_date": td,
        "symbol": sid,
        "event_type": "INTRADAY_3K_PREDICTION",
        "trigger_snapshot": {"prediction_score": score},
    }


def gt(td, sid, value):
    return {"trade_date": td, "symbol": sid, "ground_truth_3k": value}


def test_score_band_calibration_is_empirical_only():
    report = build_calibration_report(
        [pred("2026-09-23", "1111", 55), pred("2026-09-23", "2222", 82), pred("2026-09-23", "3333", 91)],
        [gt("2026-09-23", "1111", False), gt("2026-09-23", "2222", True), gt("2026-09-23", "3333", True)],
    )
    assert report["sample_count"] == 3
    assert report["hit_count"] == 2
    assert report["empirical_hit_rate"] == 2 / 3
    assert report["probability_claim"] is False
    assert report["method"] == "historical_empirical_hit_rate"
    assert report["bands"][0]["sample_count"] == 1
    assert report["bands"][3]["empirical_hit_rate"] == 1.0
    assert report["bands"][4]["empirical_hit_rate"] == 1.0


def test_unmatched_and_invalid_are_excluded_from_calibration():
    report = build_calibration_report(
        [pred("2026-09-23", "1111", 75), pred("2026-09-23", "2222", 101), pred("2026-09-23", "3333", 85)],
        [gt("2026-09-23", "1111", True)],
    )
    assert report["sample_count"] == 1
    assert report["unmatched_ground_truth"] == 1
    assert report["invalid_score"] == 1
