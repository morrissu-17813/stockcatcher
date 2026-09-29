import time

import pytest

from tianji_3k.data.finmind_budget import FinMindBudgetExceeded, FinMindRequestBudget


def test_budget_blocks_at_580(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    budget = FinMindRequestBudget(limit=580, window_seconds=3600)
    for _ in range(580):
        budget.reserve("test")
    with pytest.raises(FinMindBudgetExceeded):
        budget.reserve("overflow")
    assert budget.snapshot()["used"] == 580


def test_budget_releases_after_rolling_window(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    budget = FinMindRequestBudget(limit=580, window_seconds=3600)
    for _ in range(580):
        budget.reserve("test")
    clock[0] += 3600.1
    assert budget.snapshot()["used"] == 0
    budget.reserve("after-window")
    assert budget.snapshot()["used"] == 1
