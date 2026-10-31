from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd

from stockcatcher import technical_indicator_engine as engine_module


def test_intraday_breakout_does_not_replace_daily_trend_condition():
    engine = engine_module.TechnicalSignalEngine(api_key="test")
    snapshot = {
        "close": 120.0,
        "daily_close": 90.0,
        "score": 70.0,
        "daily_score": 70.0,
        "ma5": 100.0,
        "ma20": 95.0,
        "rsi14": 40.0,
        "macd_hist": -1.0,
        "is_3k_breakout": False,
        "daily_is_3k_breakout": False,
        "is_5k_breakout": False,
        "daily_is_5k_breakout": False,
    }
    effective_3k = {"close": 119.0, "breakout_price": 118.0}

    decision = engine.evaluate_alert_triggers(
        "2330",
        snapshot=snapshot,
        effective_3k=effective_3k,
    )

    assert decision["three_k_confirmed"] is True
    assert decision["tier1_base"] is False
    assert decision["should_send"] is False


def test_intraday_score_is_separate_from_daily_score():
    snapshot = {"close": 120.0}
    effective_3k = {
        "close": 119.0,
        "breakout_price": 118.0,
        "volume_ratio": 1.8,
        "ma5": 105.0,
        "ma20": 110.0,
    }

    intraday_score = engine_module.WarrantTelegramAlertRunner._score_intraday_setup(
        snapshot,
        effective_3k,
        same_time_volume_flag=False,
    )

    assert intraday_score["score"] == 85
    assert intraday_score["components"]["same_time_volume_flag"] == 0


def test_missing_same_time_baseline_does_not_block_alert():
    engine = engine_module.TechnicalSignalEngine(api_key="test")
    snapshot = {
        "close": 105.0,
        "daily_close": 105.0,
        "score": 70.0,
        "daily_score": 70.0,
        "ma5": 100.0,
        "ma20": 95.0,
        "rsi14": 55.0,
        "macd_hist": 1.0,
        "daily_is_3k_breakout": False,
        "daily_is_5k_breakout": False,
        "same_time_volume_available": False,
        "volume_ratio": 0.0,
    }

    decision = engine.evaluate_alert_triggers(
        "2330",
        snapshot=snapshot,
        effective_3k={"close": 101.0, "breakout_price": 100.0},
    )

    assert decision["should_send"] is True
    assert decision["same_time_volume_flag"] is False


def test_tdcc_holder_change_uses_latest_two_fresh_reports():
    rows = [
        {"symbol": "2330", "date": "20261027", "ratio_400k": 52.35, "ratio_1000k": 28.10},
        {"symbol": "2330", "date": "20261020", "ratio_400k": 52.15, "ratio_1000k": 28.00},
    ]
    response = SimpleNamespace(json=lambda: rows)
    now = datetime(2026, 11, 1, tzinfo=engine_module.TAIPEI_TIMEZONE)

    with patch.object(engine_module, "request_get", return_value=response):
        changes = engine_module.FundamentalChipDataLayer.fetch_tdcc_big_holder_changes(
            ["2330"], now=now
        )

    assert changes["2330"]["tdcc_available"] is True
    assert changes["2330"]["big_holder_change_400k_pp"] == 0.2
    assert changes["2330"]["big_holder_change_1000k_pp"] == 0.1


def test_tier3_requires_insider_streak_and_positive_tdcc_change():
    engine = engine_module.TechnicalSignalEngine(api_key="test")
    snapshot = {
        "close": 105.0,
        "daily_close": 105.0,
        "daily_score": 70.0,
        "ma5": 100.0,
        "ma20": 95.0,
        "rsi14": 55.0,
        "macd_hist": 1.0,
    }
    insider = {"net_buy": 1000.0, "buy_count": 3, "buy_streak": 3}
    effective_3k = {"close": 101.0, "breakout_price": 100.0}
    chip = {
        "tdcc_available": True,
        "big_holder_change_400k_pp": 0.2,
        "big_holder_ratio_400k": 52.35,
    }

    decision = engine.evaluate_alert_triggers(
        "2330", snapshot=snapshot, effective_3k=effective_3k,
        insider=insider, chip=chip,
    )
    assert decision["tier3_ultimate"] is True
    assert decision["tier_level"] == 3

    chip["big_holder_change_400k_pp"] = 0.0
    decision = engine.evaluate_alert_triggers(
        "2330", snapshot=snapshot, effective_3k=effective_3k,
        insider=insider, chip=chip,
    )
    assert decision["tier3_ultimate"] is False
    assert decision["tier_level"] == 2

    chip["big_holder_change_400k_pp"] = 0.2
    insider["buy_streak"] = 2
    decision = engine.evaluate_alert_triggers(
        "2330", snapshot=snapshot, effective_3k=effective_3k,
        insider=insider, chip=chip,
    )
    assert decision["tier3_ultimate"] is False
    assert decision["tier_level"] == 2


def test_build_signal_snapshot_exposes_daily_score_and_daily_flags():
    engine = engine_module.TechnicalSignalEngine(api_key="test")
    dates = pd.date_range("2026-09-01", periods=30, freq="D")
    closes = [float(80 + index) for index in range(30)]
    daily_bars = pd.DataFrame({
        "date": dates,
        "open": closes,
        "high": [value + 1 for value in closes],
        "low": [value - 1 for value in closes],
        "close": closes,
        "volume": [1000.0] * len(closes),
    })

    snapshot = engine.build_signal_snapshot("2330", daily_bars)

    assert snapshot["daily_score"] == snapshot["score"]
    assert snapshot["daily_close"] == snapshot["close"]
    assert snapshot["daily_is_3k_breakout"] == snapshot["is_3k_breakout"]
    assert snapshot["daily_is_5k_breakout"] == snapshot["is_5k_breakout"]


def test_safe_snapshot_uses_only_completed_daily_bars():
    runner = engine_module.WarrantTelegramAlertRunner(quota=1, chat_id="test")
    now = datetime(2026, 11, 3, 10, 0, tzinfo=engine_module.TAIPEI_TIMEZONE)
    dates = pd.date_range(end=pd.Timestamp(now).normalize(), periods=30, freq="D")
    closes = [90.0] * 28 + [100.0, 200.0]
    runner.engine.cache["2330"] = pd.DataFrame({
        "date": dates,
        "open": closes,
        "high": [value + 1 for value in closes],
        "low": [value - 1 for value in closes],
        "close": closes,
        "volume": [1000.0] * len(closes),
    })

    with patch.object(engine_module, "get_taipei_now", return_value=now):
        snapshot = runner._safe_snapshot(
            "2330",
            {"current_price": 101.0, "total_vol": 500.0},
        )

    assert snapshot["daily_close"] == 100.0
    assert snapshot["close"] == 101.0
    assert snapshot["daily_score"] == snapshot["score"]


def test_run_cycle_preserves_daily_breakout_flag_and_emits_both_scores():
    runner = engine_module.WarrantTelegramAlertRunner(quota=1, chat_id="test")
    hit = {"sid": "2330", "name": "Test", "current_price": 120.0, "total_vol": 1000}
    effective_3k = {
        "bar_time": "2026-10-30T10:00:00+08:00",
        "close": 119.0,
        "breakout_price": 118.0,
        "volume": 180.0,
        "volume_ratio": 1.8,
        "ma5": 115.0,
        "ma20": 110.0,
        "completed_day_volume": 1000.0,
    }
    daily_snapshot = {
        "close": 120.0,
        "daily_close": 105.0,
        "score": 70.0,
        "daily_score": 70.0,
        "is_3k_breakout": False,
        "daily_is_3k_breakout": False,
        "is_5k_breakout": False,
        "daily_is_5k_breakout": False,
        "ma5": 100.0,
        "ma20": 95.0,
        "rsi14": 55.0,
        "macd_hist": 1.0,
        "trend": "bullish",
    }
    runner.monitor.scan_mis_for_warrant_hedge = lambda symbols: [hit]
    runner._safe_snapshot = lambda symbol, row: dict(daily_snapshot)
    runner._get_same_time_volume_baseline = lambda symbol, volume: {
        "median_volume": 600.0,
        "volume_ratio": 1.6,
    }
    runner._get_cached_insider_buy_data = lambda: {}
    runner._get_cached_tdcc_big_holder_changes = lambda symbols: {
        symbol: {"tdcc_available": False} for symbol in symbols
    }
    sent_messages = []

    with patch.object(
        engine_module,
        "fetch_effective_3k_breakouts",
        return_value={"2330": effective_3k},
    ), patch.object(
        engine_module,
        "send_telegram_message",
        side_effect=lambda message, **kwargs: (
            sent_messages.append(message) or {"status_code": 200, "body": {"ok": True}}
        ),
    ):
        alerts = runner.run_cycle(["2330"])

    assert len(alerts) == 1
    assert alerts[0]["decision"]["snapshot"]["is_3k_breakout"] is False
    assert alerts[0]["decision"]["snapshot"]["effective_3k_confirmed"] is True
    assert alerts[0]["decision"]["daily_score"] == 70.0
    assert alerts[0]["decision"]["intraday_score"] == 100
    assert len(sent_messages) == 1


def test_run_cycle_wires_tdcc_change_into_tier3_notification():
    runner = engine_module.WarrantTelegramAlertRunner(quota=1, chat_id="test")
    hit = {"sid": "2330", "name": "Test", "current_price": 120.0, "total_vol": 1000}
    effective_3k = {
        "bar_time": "2026-10-30T10:00:00+08:00",
        "close": 119.0,
        "breakout_price": 118.0,
        "volume": 180.0,
        "volume_ratio": 1.8,
        "ma5": 115.0,
        "ma20": 110.0,
        "completed_day_volume": 1000.0,
    }
    daily_snapshot = {
        "close": 120.0,
        "daily_close": 105.0,
        "score": 70.0,
        "daily_score": 70.0,
        "daily_is_3k_breakout": False,
        "daily_is_5k_breakout": False,
        "ma5": 100.0,
        "ma20": 95.0,
        "rsi14": 55.0,
        "macd_hist": 1.0,
        "trend": "bullish",
    }
    runner.monitor.scan_mis_for_warrant_hedge = lambda symbols: [hit]
    runner._safe_snapshot = lambda symbol, row: dict(daily_snapshot)
    runner._get_same_time_volume_baseline = lambda symbol, volume: None
    runner._get_cached_insider_buy_data = lambda: {
        "2330": {"net_buy": 10000.0, "buy_count": 3, "buy_streak": 3, "buy_names": ["X"]}
    }
    tdcc_signal = {
        "tdcc_available": True,
        "tdcc_latest_date": "20261027",
        "tdcc_previous_date": "20261020",
        "big_holder_ratio_400k": 52.35,
        "big_holder_ratio_1000k": 28.1,
        "big_holder_change_400k_pp": 0.2,
        "big_holder_change_1000k_pp": 0.1,
    }
    runner._get_cached_tdcc_big_holder_changes = lambda symbols: {"2330": tdcc_signal}
    sent_messages = []

    with patch.object(
        engine_module,
        "fetch_effective_3k_breakouts",
        return_value={"2330": effective_3k},
    ), patch.object(
        engine_module,
        "send_telegram_message",
        side_effect=lambda message, **kwargs: (
            sent_messages.append(message) or {"status_code": 200, "body": {"ok": True}}
        ),
    ):
        alerts = runner.run_cycle(["2330"])

    assert len(alerts) == 1
    assert alerts[0]["decision"]["tier_level"] == 3
    assert alerts[0]["chip_source"] == "FinMind內部人+Supabase TDCC"
    assert "+0.20" in sent_messages[0]
    assert "Tier 3" in sent_messages[0]