import json
from pathlib import Path

import pytest

from tianji_3k.data.finmind_budget import FinMindRequestBudget
from tianji_3k.data.finmind_initialization import ProductionCacheInitializer


class FakeCalendar:
    def __init__(self):
        self.last_snapshot = object()

    def refresh(self, force=False):
        return None

    def latest_completed(self):
        return "2026-09-24"

    def previous_trading_days(self, end_date, bars, include_end=True):
        return [__import__("datetime").date(2026, 9, 22), __import__("datetime").date(2026, 9, 23), __import__("datetime").date(2026, 9, 24)][-bars:]


class FakeUniverse:
    def fetch(self):
        return [
            {"symbol": "1001", "security_type": "common_stock"},
            {"symbol": "1002", "security_type": "common_stock"},
            {"symbol": "1003", "security_type": "common_stock"},
            {"symbol": "ETF1", "security_type": "common_stock"},
            {"symbol": "1004", "security_type": "warrant"},
        ]


class BudgetedProvider:
    def __init__(self, budget, complete=None):
        self.budget = budget
        self.complete = set(complete or [])
        self.calls = []

    def get_daily(self, symbol, start, end):
        self.calls.append(symbol)
        if symbol not in self.complete:
            self.budget.reserve(f"test:{symbol}")
            self.complete.add(symbol)
        return []


def make_initializer(tmp_path, budget, provider, universe=None):
    return ProductionCacheInitializer(
        cache_dir=tmp_path / "daily",
        checkpoint_path=tmp_path / "production_cache_initialization.json",
        budget=budget,
        calendar=FakeCalendar(),
        provider=provider,
        universe_provider=universe or FakeUniverse(),
        sleep_fn=lambda _: None,
        min_universe_symbols=0,
    )


def test_budget_pause_writes_checkpoint(tmp_path, monkeypatch):
    import tianji_3k.data.finmind_budget as fb
    clock = [1000.0]
    monkeypatch.setattr(fb.time, "monotonic", lambda: clock[0])
    budget = FinMindRequestBudget(limit=2, window_seconds=3600)
    provider = BudgetedProvider(budget)
    init = make_initializer(tmp_path, budget, provider)

    result = init.initialize("2026-09-25", bars_required=3, wait_for_budget=False)

    assert result.status == "PAUSED_BUDGET"
    assert result.completed_symbols == 2
    assert result.pending_symbols == 1
    payload = json.loads((tmp_path / "production_cache_initialization.json").read_text(encoding="utf-8"))
    assert payload["status"] == "PAUSED_BUDGET"
    assert payload["current_symbol"] == "1003"
    assert payload["pending_symbols"] == ["1003"]


def test_resume_skips_completed_symbols_and_finishes(tmp_path, monkeypatch):
    import tianji_3k.data.finmind_budget as fb
    clock = [1000.0]
    monkeypatch.setattr(fb.time, "monotonic", lambda: clock[0])
    budget = FinMindRequestBudget(limit=2, window_seconds=3600)
    provider = BudgetedProvider(budget)
    init = make_initializer(tmp_path, budget, provider)

    first = init.initialize("2026-09-25", bars_required=3, wait_for_budget=False)
    assert first.status == "PAUSED_BUDGET"

    clock[0] += 3600.1
    second = init.initialize("2026-09-25", bars_required=3, wait_for_budget=False)
    assert second.status == "COMPLETE"
    assert second.completed_symbols == 3
    assert provider.calls == ["1001", "1002", "1003"]

    payload = json.loads((tmp_path / "production_cache_initialization.json").read_text(encoding="utf-8"))
    assert payload["status"] == "COMPLETE"
    assert payload["pending_symbols"] == []


def test_existing_completed_cache_symbols_do_not_consume_budget(tmp_path):
    budget = FinMindRequestBudget(limit=1)
    provider = BudgetedProvider(budget, complete={"1001", "1002", "1003"})
    init = make_initializer(tmp_path, budget, provider)

    result = init.initialize("2026-09-25", bars_required=3, wait_for_budget=False)

    assert result.status == "COMPLETE"
    assert result.requests_used == 0
    assert provider.calls == ["1001", "1002", "1003"]


def test_seconds_until_available_tracks_oldest_request(monkeypatch):
    import tianji_3k.data.finmind_budget as fb
    clock = [1000.0]
    monkeypatch.setattr(fb.time, "monotonic", lambda: clock[0])
    budget = FinMindRequestBudget(limit=2, window_seconds=3600)
    budget.reserve("a")
    budget.reserve("b")
    assert budget.seconds_until_available() == pytest.approx(3600.0)
    clock[0] += 3599.5
    assert budget.seconds_until_available() == pytest.approx(0.5)
    clock[0] += 0.6
    assert budget.seconds_until_available() == 0.0


def test_wait_for_budget_auto_resumes_after_rolling_window(tmp_path, monkeypatch):
    import tianji_3k.data.finmind_budget as fb
    clock = [1000.0]
    monkeypatch.setattr(fb.time, "monotonic", lambda: clock[0])
    budget = FinMindRequestBudget(limit=2, window_seconds=3600)
    provider = BudgetedProvider(budget)

    def advance(seconds):
        clock[0] += seconds

    init = ProductionCacheInitializer(
        cache_dir=tmp_path / "daily",
        checkpoint_path=tmp_path / "production_cache_initialization.json",
        budget=budget,
        calendar=FakeCalendar(),
        provider=provider,
        universe_provider=FakeUniverse(),
        sleep_fn=advance,
        min_universe_symbols=0,
    )
    result = init.initialize("2026-09-25", bars_required=3, wait_for_budget=True)

    assert result.status == "COMPLETE"
    assert result.completed_symbols == 3
    assert clock[0] >= 4600.0
    assert provider.calls == ["1001", "1002", "1003"]


def test_error_is_checkpointed_before_propagation(tmp_path):
    class FailingProvider(BudgetedProvider):
        def get_daily(self, symbol, start, end):
            self.calls.append(symbol)
            raise RuntimeError("simulated network failure")

    budget = FinMindRequestBudget(limit=2)
    init = make_initializer(tmp_path, budget, FailingProvider(budget))
    with pytest.raises(RuntimeError, match="simulated network failure"):
        init.initialize("2026-09-25", bars_required=3, wait_for_budget=False)

    payload = json.loads((tmp_path / "production_cache_initialization.json").read_text(encoding="utf-8"))
    assert payload["status"] == "PAUSED_ERROR"
    assert payload["current_symbol"] == "1001"
    assert payload["pending_symbols"][0] == "1001"
