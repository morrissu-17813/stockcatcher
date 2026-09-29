import json
from pathlib import Path

import pandas as pd

from tianji_3k.data.cache_first import CacheFirstDailyProvider


def make_rows(start="2026-03-24", end="2026-09-20"):
    dates = pd.date_range(start, end, freq="D")
    return pd.DataFrame({
        "date": dates,
        "stock_id": "TEST",
        "Trading_Volume": 2_000_000,
        "open": 100.0,
        "max": 105.0,
        "min": 99.0,
        "close": 104.0,
    })


def write_cache(path: Path, df: pd.DataFrame):
    path.write_text(df.to_json(orient="records", date_format="iso"), encoding="utf-8")


class FakeFallback:
    def __init__(self):
        self.calls = []

    def get_daily(self, symbol, start, end):
        self.calls.append((symbol, start, end))
        return pd.DataFrame({
            "date": pd.date_range(start, end, freq="D"),
            "stock_id": symbol,
            "Trading_Volume": 2_000_000,
            "open": 101.0,
            "max": 106.0,
            "min": 100.0,
            "close": 105.0,
        })


def test_tail_increment_only(tmp_path):
    cache = tmp_path / "daily"
    cache.mkdir()
    write_cache(cache / "TaiwanStockPrice_1234_2026-03-24_2026-09-20.json", make_rows())

    provider = CacheFirstDailyProvider("", cache_dir=cache)
    fake = FakeFallback()
    provider.fallback = fake

    df = provider.get_daily("1234", "2026-03-25", "2026-09-21")
    assert not df.empty
    assert fake.calls == [("1234", "2026-09-21", "2026-09-21")]
    assert provider.cache_partial == 1
    assert provider.finmind_fallbacks == 1
    assert provider.cache_updates == 1
    assert df["date"].min().strftime("%Y-%m-%d") == "2026-03-25"
    assert df["date"].max().strftime("%Y-%m-%d") == "2026-09-21"

    # Second call should be a pure cache hit; no second FinMind request.
    df2 = provider.get_daily("1234", "2026-03-25", "2026-09-21")
    assert fake.calls == [("1234", "2026-09-21", "2026-09-21")]
    assert provider.cache_hits == 1
    assert len(df2) >= len(df) - 1


def test_full_miss_is_one_request(tmp_path):
    cache = tmp_path / "daily"
    cache.mkdir()
    provider = CacheFirstDailyProvider("", cache_dir=cache)
    fake = FakeFallback()
    provider.fallback = fake

    df = provider.get_daily("5678", "2026-09-01", "2026-09-21")
    assert not df.empty
    assert fake.calls == [("5678", "2026-09-01", "2026-09-21")]
    assert provider.cache_misses == 1
    assert provider.finmind_fallbacks == 1
    assert provider.cache_updates == 1
