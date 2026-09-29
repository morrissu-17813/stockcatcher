import json
from pathlib import Path

import pandas as pd
import pytest

from tianji_3k.data.trading_calendar import TaiwanTradingCalendar
from tianji_3k.data.cache_first import CacheFirstDailyProvider
from tianji_3k.data.data_integrity import validate_k012
from tianji_3k.stage2.breakout_engine import evaluate as evaluate_stage2


def make_calendar(tmp_path: Path, dates):
    p = tmp_path / "trading_calendar.json"
    p.write_text(json.dumps({"dates": [d.isoformat() for d in dates]}), encoding="utf-8")
    return TaiwanTradingCalendar(token="", cache_path=p)


def test_calendar_is_source_of_expected_dates(tmp_path):
    cal = make_calendar(tmp_path, [pd.Timestamp("2026-09-18").date(), pd.Timestamp("2026-09-21").date(), pd.Timestamp("2026-09-22").date(), pd.Timestamp("2026-09-23").date()])
    assert [d.isoformat() for d in cal.expected_trading_days("2026-09-18", "2026-09-23")] == ["2026-09-18", "2026-09-21", "2026-09-22", "2026-09-23"]
    assert [d.isoformat() for d in cal.previous_trading_days("2026-09-23", 3)] == ["2026-09-21", "2026-09-22", "2026-09-23"]


def test_cache_backfills_missing_trading_day(tmp_path):
    daily = tmp_path / "daily"
    daily.mkdir()
    dates = [pd.Timestamp("2026-09-18").date(), pd.Timestamp("2026-09-21").date(), pd.Timestamp("2026-09-22").date(), pd.Timestamp("2026-09-23").date()]
    cal = make_calendar(tmp_path, dates)
    path = daily / "TaiwanStockPrice_1101_2026-09-18_2026-09-23.json"
    path.write_text(json.dumps([
        {"date": "2026-09-18", "open": 24, "high": 25, "low": 23, "close": 24.5, "volume": 1000},
        {"date": "2026-09-21", "open": 24, "high": 24.55, "low": 23.8, "close": 24.2, "volume": 1000},
        {"date": "2026-09-23", "open": 24.85, "high": 26.1, "low": 24.5, "close": 25.65, "volume": 2000},
    ]), encoding="utf-8")
    provider = CacheFirstDailyProvider("", daily, cal)
    fetched = pd.DataFrame([{"date": "2026-09-22", "open": 24.1, "high": 24.55, "low": 23.9, "close": 24.4, "volume": 1200}])
    provider.fallback.get_daily = lambda symbol, start, end: fetched.copy()
    out = provider.get_daily("1101", "2026-09-21", "2026-09-23")
    assert [str(x)[:10] for x in out.date] == ["2026-09-21", "2026-09-22", "2026-09-23"]
    assert provider.last_source == "cache+finmind"


def test_stage2_rejects_missing_k1_k2_dates(tmp_path):
    cal = make_calendar(tmp_path, [pd.Timestamp("2026-09-18").date(), pd.Timestamp("2026-09-21").date(), pd.Timestamp("2026-09-23").date()])
    rows = {
        "2026-09-18": {"date": "2026-09-18", "open": 20, "high": 21, "low": 19, "close": 20},
        "2026-09-23": {"date": "2026-09-23", "open": 24, "high": 26, "low": 23, "close": 25},
    }
    result, err = evaluate_stage2(rows, cal)
    assert result is None
    assert err == "K012_MISSING"


def test_stage2_records_k012_dates(tmp_path):
    cal = make_calendar(tmp_path, [pd.Timestamp("2026-09-21").date(), pd.Timestamp("2026-09-22").date(), pd.Timestamp("2026-09-23").date()])
    rows = {
        d: {"date": d, "open": 10, "high": 11 + i, "low": 9, "close": 10 + i}
        for i, d in enumerate(["2026-09-21", "2026-09-22", "2026-09-23"])
    }
    result, err = evaluate_stage2(rows, cal)
    assert err is None
    assert result["k0_date"] == "2026-09-23"
    assert result["k1_date"] == "2026-09-22"
    assert result["k2_date"] == "2026-09-21"
