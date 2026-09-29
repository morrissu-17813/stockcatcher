from datetime import date
from types import SimpleNamespace

import pandas as pd

from tianji_3k.data.cache_first import CacheFirstDailyProvider
from tianji_3k.data.daily_refresh import DailyDataRefreshManager
from tianji_3k.data.finmind_budget import FinMindBudgetExceeded, FinMindRequestBudget


class FakeCalendar:
    def expected_trading_days(self, start, end):
        return [date(2026, 9, 21), date(2026, 9, 22), date(2026, 9, 23), date(2026, 9, 24)]

    def previous_trading_days(self, end, count, include_end=True):
        return [date(2026, 9, 21), date(2026, 9, 22), date(2026, 9, 23), date(2026, 9, 24)]


def _bars(dates):
    return pd.DataFrame(
        [
            {
                "date": d,
                "open": 10.0,
                "high": 11.0,
                "low": 9.0,
                "close": 10.5,
                "volume": 100000,
            }
            for d in dates
        ]
    )


def test_sparse_cache_uses_one_finmind_request_per_symbol(tmp_path):
    provider = CacheFirstDailyProvider(
        token="x", cache_dir=tmp_path, calendar=FakeCalendar(), budget=FinMindRequestBudget(limit=580)
    )
    provider._write_merged_cache("1234", _bars(["2026-09-21", "2026-09-23", "2026-09-24"]))

    calls = []

    def fake_get_daily(symbol, start, end):
        calls.append((symbol, start, end))
        return _bars(["2026-09-21", "2026-09-22", "2026-09-23", "2026-09-24"])

    provider.fallback.get_daily = fake_get_daily
    result = provider.get_daily("1234", "2026-09-21", "2026-09-24")

    assert len(calls) == 1
    assert calls[0] == ("1234", "2026-09-21", "2026-09-24")
    assert len(result) == 4
    assert provider.finmind_fallbacks == 1


def test_refresh_without_symbols_does_not_walk_cache(tmp_path):
    manager = DailyDataRefreshManager(tmp_path, tmp_path / "freshness.json", token="x", budget=FinMindRequestBudget(limit=580))
    manager.calendar = SimpleNamespace(
        refresh=lambda force=False: SimpleNamespace(rows=100),
        last_snapshot=None,
    )
    manager.resolver = SimpleNamespace(resolve=lambda: "2026-09-24")

    calls = []
    manager.provider.get_daily = lambda *args: calls.append(args)

    result = manager.refresh("2026-09-27")

    assert result.status == "READY"
    assert result.symbols_requested == 0
    assert calls == []


def test_budget_block_is_distinct_from_history_failure(tmp_path):
    manager = DailyDataRefreshManager(tmp_path, tmp_path / "freshness.json", token="x", budget=FinMindRequestBudget(limit=580))
    manager.calendar = FakeCalendar()

    def blocked(*args, **kwargs):
        raise FinMindBudgetExceeded("budget")

    manager.provider.get_daily = blocked
    result = manager.ensure_history(["1234"], "2026-09-24", 4)

    assert result["failed"] == 0
    assert result["budget_blocked"] == 1
    assert result["repaired"] == 0
    assert result["errors"][0]["error_type"] == "FinMindBudgetExceeded"
