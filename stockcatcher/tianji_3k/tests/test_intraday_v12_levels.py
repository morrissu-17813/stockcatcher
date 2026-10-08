from tianji_3k.notification.gate import evaluate_intraday_notification

def test_v12_notification_levels():
    assert evaluate_intraday_notification(4.0).status == "READY"
    assert evaluate_intraday_notification(9.5).status == "MOMENTUM"

def test_v12_threshold_constants_in_runner_source():
    from pathlib import Path
    source = Path(__file__).parents[1].joinpath("runner.py").read_text()
    assert "min_volume_ratio=1.05" in source
    assert "projected_strong" in source
    assert "projected_early" in source
    assert "micro_structure or micro_volume" in source or "structure_pass" in source
    assert "EARLY is intentionally not gated by projected volume" in source
    assert ">= 1.30" in source
    assert ">= 1.50" in source
