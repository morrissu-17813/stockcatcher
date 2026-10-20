from signal_validation import validate_signal_daily


def test_daily_signal_validation_uses_only_bars_after_signal():
    bars = [
        {"date":"2026-10-07","open":229.5,"high":250.5,"low":227,"close":250.5},
        {"date":"2026-10-08","open":247.5,"high":256,"low":240.5,"close":248},
        {"date":"2026-10-09","open":248,"high":251,"low":245,"close":250},
        {"date":"2026-10-12","open":251,"high":272.5,"low":251,"close":272.5},
    ]
    result = validate_signal_daily("6278", "2026-10-07", 250.5, bars, horizon_days=7)
    assert result["ok"]
    assert result["observation_start"] == "2026-10-08"
    assert result["signal_reference_excursion"]["max_high"] == 272.5
    assert result["next_trading_day_open_scenario"]["entry_price"] == 247.5
    assert result["next_trading_day_open_scenario"]["stop_scenario"]["triggered"] is True
    assert result["paper_orders_created"] == 0


def test_signal_validation_missing_signal_day_is_incomplete():
    result = validate_signal_daily("6278", "2026-10-07", 250.5, [
        {"date":"2026-10-08","open":247.5,"high":256,"low":240.5,"close":248}
    ])
    assert result["ok"] is False
    assert result["status"] == "DATA_INCOMPLETE"
