from pathlib import Path

from tianji_3k.core.failure_injection import FailureInjector, write_report


def test_full_day_failure_injection_passes(tmp_path):
    result = FailureInjector(tmp_path / "run").run()
    assert result.passed is True
    assert result.processed_steps == 10
    assert result.recovery_count >= 2
    assert result.predictions_created >= 2
    assert result.validation_count == result.predictions_created
    assert "PROCESS_CRASH_AFTER_PREDICTION" in result.failures_injected
    assert "TELEGRAM_SEND_FAILURE" in result.failures_injected
    assert not result.errors


def test_failure_injection_report_is_replayable(tmp_path):
    result = FailureInjector(tmp_path / "run").run()
    report = write_report(result, tmp_path / "report.json")
    assert report.exists()
    text = report.read_text(encoding="utf-8")
    assert '"passed": true' in text
    assert '"PREDICTION_VALIDATION"' not in text  # report is operational; ledger owns chain records
