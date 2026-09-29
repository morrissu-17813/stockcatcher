from tianji_3k.stage2.breakout_engine import evaluate
from tianji_3k.stage3.volume_engine import eval_volume


def test_stage2_pass():
    rows = {
        "2026-09-16": {
            "date": "2026-09-16",
            "open": 90,
            "high": 95,
            "close": 94,
        },
        "2026-09-17": {
            "date": "2026-09-17",
            "open": 96,
            "high": 100,
            "close": 98,
        },
        "2026-09-18": {
            "date": "2026-09-18",
            "open": 101,
            "high": 110,
            "close": 106,
        },
    }

    result, error = evaluate(rows)

    assert error is None
    assert result["pass"] is True
    assert result["k0_date"] == "2026-09-18"
    assert result["k1_date"] == "2026-09-17"
    assert result["k2_date"] == "2026-09-16"


def test_stage2_reject():
    rows = {
        "2026-09-16": {
            "date": "2026-09-16",
            "open": 1,
            "high": 2,
            "close": 1.1,
        },
        "2026-09-17": {
            "date": "2026-09-17",
            "open": 1,
            "high": 3,
            "close": 1.2,
        },
        "2026-09-18": {
            "date": "2026-09-18",
            "open": 1,
            "high": 4,
            "close": 1.3,
        },
    }

    result, error = evaluate(rows)

    assert error is None
    assert result["pass"] is False
    assert result["first_fail"] is not None


def test_stage3_pass():
    result = eval_volume(
        {
            "1": 1_000_000,
            "2": 1_000_000,
            "3": 1_100_000,
            "4": 1_200_000,
            "5": 1_300_000,
            "6": 3_000_000,
        }
    )

    assert result["pass"] is True


def test_stage3_fail_ratio():
    result = eval_volume(
        {
            "1": 1_000_000,
            "2": 1_000_000,
            "3": 1_000_000,
            "4": 1_000_000,
            "5": 1_000_000,
            "6": 1_200_000,
        }
    )

    assert result["pass"] is False
