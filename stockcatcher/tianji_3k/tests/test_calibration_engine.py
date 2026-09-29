from tianji_3k.validation.calibration_engine import PredictionCalibrationEngine


def p(td, sid, score, created="2026-09-23T09:30:00+08:00", pid=None):
    return {
        "prediction_id": pid or f"{td}-{sid}-{score}",
        "trade_date": td,
        "symbol": sid,
        "created_at": created,
        "trigger_snapshot": {"prediction_score": score},
    }


def g(td, sid, hit):
    return {"trade_date": td, "symbol": sid, "ground_truth_3k": hit}


def test_engine_produces_score_and_time_calibration():
    preds = [
        p("2026-09-23", "1111", 55, "2026-09-23T09:30:00+08:00"),
        p("2026-09-23", "2222", 82, "2026-09-23T11:20:00+08:00"),
        p("2026-09-23", "3333", 91, "2026-09-23T13:05:00+08:00"),
    ]
    gts = [g("2026-09-23", "1111", False), g("2026-09-23", "2222", True), g("2026-09-23", "3333", True)]
    report = PredictionCalibrationEngine(min_samples_for_stable_band=2).build_report(preds, gts)
    assert report["matched_count"] == 3
    assert report["hit_count"] == 2
    assert report["probability_claim"] is False
    assert report["score_bands"][0]["sample_count"] == 1
    assert report["trigger_time_bands"][0]["sample_count"] == 1
    assert report["trigger_time_bands"][2]["sample_count"] == 1
    assert report["score_bands"][0]["stable_sample"] is False


def test_engine_excludes_invalid_and_unmatched():
    preds = [p("2026-09-23", "1111", 75), p("2026-09-23", "2222", 101), p("2026-09-23", "3333", 85)]
    gts = [g("2026-09-23", "1111", True)]
    report = PredictionCalibrationEngine().build_report(preds, gts)
    assert report["matched_count"] == 1
    assert report["invalid_score"] == 1
    assert report["unmatched_ground_truth"] == 1
    assert report["empirical_hit_rate"] == 1.0


def test_wilson_interval_is_bounded():
    report = PredictionCalibrationEngine().build_report([p("2026-09-23", "1111", 90)], [g("2026-09-23", "1111", True)])
    assert 0.0 <= report["wilson_95_low"] <= report["wilson_95_high"] <= 1.0
