from decision_journal import build_decision, build_journal


def sample_signal(**overrides):
    row = {
        "prediction_id": "pred-abc-123", "event_id": "event-abc", "symbol": "2330", "name": "台積電",
        "trade_date": "2026-10-16", "created_at": "2026-10-16T09:15:00+08:00",
        "source_path": "predictions/2026-10-16/2330/events.jsonl", "current_price": 1500,
        "up_pct": 2.1, "projected_ratio": 2.4, "live_volume_ratio": 1.8,
        "signal_level": "EARLY", "stage0_pass": False, "stage1_pass": True,
        "stage2_pass": False, "stage3_pass": False, "dynamic_candidate": True,
        "notification_status": "SENT", "validation_status": "GROUND_TRUTH_UNAVAILABLE_AT_CUTOFF",
        "ground_truth_available": False, "ground_truth_3k": None,
        "validation_source_path": "validation/master_prediction_validation_log.jsonl",
    }
    row.update(overrides)
    return row


def test_build_decision_has_six_role_specific_traceable_records():
    journal = build_decision(sample_signal())
    assert journal["agent_count"] == 6
    assert {r["agent_id"] for r in journal["records"]} == {"cio", "quant", "research", "risk", "execution", "auditor"}
    assert all(r["prediction_id"] == "pred-abc-123" for r in journal["records"])
    assert all(r["decision_id"] and r["source_path"].endswith("events.jsonl") for r in journal["records"])
    assert journal["risk_flags"] and "VALIDATION_PENDING" in journal["risk_flags"]
    assert journal["records"][4]["decision_status"] == "NO_ORDER"
    assert journal["records"][5]["decision_status"] == "INCOMPLETE_EVIDENCE"


def test_does_not_claim_ground_truth_or_external_ai_when_missing():
    journal = build_decision(sample_signal())
    assert journal["records"][0]["ground_truth_available"] is False
    assert journal["records"][0]["ground_truth_3k"] is None
    assert journal["external_ai"]["gemini_used"] is False
    assert journal["external_ai"]["mcp_used"] is False
    assert any("MFE/MAE" in x for x in journal["unknowns"])


def test_journal_limits_records_and_reports_counts():
    audit = {"signals": [sample_signal(), sample_signal(prediction_id="pred-2", symbol="2317")]}
    result = build_journal(audit, limit=1)
    assert result["signal_count"] == 1
    assert result["agent_record_count"] == 6
    assert result["source_read_only"] is True


def test_missing_prediction_id_is_rejected():
    try:
        build_decision(sample_signal(prediction_id=""))
    except ValueError as exc:
        assert "prediction_id" in str(exc)
    else:
        raise AssertionError("expected prediction_id validation")


def test_gemini_is_optional_and_fails_closed_without_key(monkeypatch):
    from gemini_review import review_evidence
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    try:
        review_evidence({"prediction_id": "pred-abc-123"})
    except RuntimeError as exc:
        assert "未設定" in str(exc)
    else:
        raise AssertionError("Gemini must not run without an explicit API key")
