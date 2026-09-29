import json
from pathlib import Path

import pandas as pd

from tianji_3k.data.cache_first import CacheFirstDailyProvider


class FakeCalendar:
    def expected_trading_days(self, start, end):
        return list(pd.bdate_range(start, end).date)


class FakeFallback:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def get_daily(self, symbol, start, end):
        self.calls.append((str(symbol), start, end))
        # Deliberately ignore requested range to verify provider-side filtering.
        return pd.DataFrame(self.rows)


def row(d, close):
    return {"date": d, "open": close, "high": close + 1, "low": close - 1, "close": close, "volume": 100000}


def write_cache(path, rows):
    path.write_text(json.dumps(rows), encoding="utf-8")


def make_rows(start="2026-09-14", end="2026-09-18"):
    dates = pd.bdate_range(start, end)
    return [row(d.strftime("%Y-%m-%d"), 100 + i) for i, d in enumerate(dates)]


def test_tail_increment_only(tmp_path):
    cache = tmp_path / "daily"; cache.mkdir()
    write_cache(cache / "TaiwanStockPrice_1234_2026-03-24_2026-09-20.json", make_rows("2026-09-14", "2026-09-18") + [row("2026-09-20", 110)])
    fetched = make_rows("2026-09-21", "2026-09-21")
    p = CacheFirstDailyProvider("", cache_dir=cache, calendar=FakeCalendar())
    f = FakeFallback(fetched + make_rows("2026-09-14", "2026-09-18"))
    p.fallback = f
    out = p.get_daily("1234", "2026-09-14", "2026-09-21")
    assert f.calls == [("1234", "2026-09-21", "2026-09-21")]
    assert out.date.dt.strftime("%Y-%m-%d").tolist()[-1] == "2026-09-21"


def test_weekend_tail_only_fetches_monday(tmp_path):
    cache = tmp_path / "daily"; cache.mkdir()
    write_cache(cache / "TaiwanStockPrice_6409_2026-03-25_2026-09-18.json", make_rows())
    f = FakeFallback([row("2026-09-21", 111)])
    p = CacheFirstDailyProvider("", cache_dir=cache, calendar=FakeCalendar()); p.fallback = f
    p.get_daily("6409", "2026-09-14", "2026-09-21")
    assert f.calls == [("6409", "2026-09-21", "2026-09-21")]


def test_internal_gap_fetches_only_gap(tmp_path):
    cache = tmp_path / "daily"; cache.mkdir()
    write_cache(cache / "TaiwanStockPrice_6409_2026-09-14_2026-09-15.json", [row("2026-09-14", 100), row("2026-09-15", 101)])
    write_cache(cache / "TaiwanStockPrice_6409_2026-09-17_2026-09-18.json", [row("2026-09-17", 103), row("2026-09-18", 104)])
    f = FakeFallback([row("2026-09-16", 102)])
    p = CacheFirstDailyProvider("", cache_dir=cache, calendar=FakeCalendar()); p.fallback = f
    out = p.get_daily("6409", "2026-09-14", "2026-09-18")
    assert f.calls == [("6409", "2026-09-16", "2026-09-16")]
    assert out.date.dt.strftime("%Y-%m-%d").tolist() == ["2026-09-14", "2026-09-15", "2026-09-16", "2026-09-17", "2026-09-18"]
