from pathlib import Path

from tianji_3k.data.finmind_budget import FinMindCircuitOpen, FinMindRequestBudget


def test_finmind_budget_circuit_is_not_a_session_shutdown_signal():
    budget = FinMindRequestBudget(limit=580)
    budget.record_failure(quota=True)
    snap = budget.snapshot()
    assert snap["circuit_open"] is True
    # The liveness contract is implemented by the Runner: a PAUSED_BUDGET
    # history result is degraded, not fatal. This test locks the shared signal.
    assert snap["total_failures"] == 1


def test_final_snapshot_module_exists():
    from tianji_3k.runner import TianjiProductionRunner
    assert hasattr(TianjiProductionRunner, "_finalize_close_snapshot")


def test_radar_does_not_rebuild_when_pool_is_empty():
    from tianji_3k.runner import TianjiProductionRunner
    r = TianjiProductionRunner(telegram=False)
    r.pool = []
    r._premarket_built = True
    assert r.poll_once() == 0


def test_final_snapshot_uses_official_provider_without_finmind(tmp_path):
    from tianji_3k.runner import TianjiProductionRunner
    r = TianjiProductionRunner(telegram=False, repo_root=tmp_path)
    r.trade_date = "2026-09-28"
    calls = []
    r.data_refresh.refresh_official_daily = lambda td: calls.append(td) or {
        "status":"READY", "twse_rows":100, "tpex_rows":50,
        "rows_written":150, "errors":[]
    }
    out = r._finalize_close_snapshot()
    assert out["status"] == "READY"
    assert calls == ["2026-09-28"]
    assert r.finmind_budget.snapshot()["used"] == 0
