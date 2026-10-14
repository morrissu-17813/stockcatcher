from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from tianji_3k.core.dynamic_discovery import DynamicDiscoveryConfig
from tianji_3k.runner import TianjiProductionRunner

TAIPEI = timezone(timedelta(hours=8))


def test_dynamic_history_exception_sets_bounded_retry_backoff():
    runner = object.__new__(TianjiProductionRunner)
    runner.latest_completed_date = "2026-10-13"
    runner.trade_date = "2026-10-14"
    runner.dynamic_attempts = {}
    runner.dynamic_retry_after = {}
    runner.dynamic_contexts = {}
    runner.contexts = {}
    runner.states = {}
    runner.dynamic_discovery_config = DynamicDiscoveryConfig()
    runner.data_refresh = SimpleNamespace(
        calendar=SimpleNamespace(previous_trading_days=lambda *args, **kwargs: [datetime(2026, 8, 1).date()]),
        provider=SimpleNamespace(get_daily=lambda *args: (_ for _ in ()).throw(ValueError("FETCH_EMPTY"))),
    )
    runner.ledger = SimpleNamespace(append_event=lambda *args, **kwargs: None)
    runner._today = lambda: "2026-10-14"

    before = datetime.now(TAIPEI)
    added = runner._enrich_dynamic_candidates([{"symbol": "2323", "name": "測試股", "market": "TWSE", "up_pct": 5}])
    after = datetime.now(TAIPEI)

    assert added == 0
    assert runner.dynamic_attempts["2323"] == 1
    retry_at = datetime.fromisoformat(runner.dynamic_retry_after["2323"])
    assert before + timedelta(seconds=59) <= retry_at <= after + timedelta(seconds=61)


def test_dynamic_candidate_gate_respects_persisted_cooldown():
    runner = object.__new__(TianjiProductionRunner)
    runner.contexts = {}
    runner.dynamic_contexts = {}
    runner.dynamic_attempts = {}
    runner.dynamic_discovery_config = DynamicDiscoveryConfig()
    runner.dynamic_retry_after = {"2323": (datetime.now(TAIPEI) + timedelta(minutes=2)).isoformat()}

    raw = {"2323": {"up_pct": 5.0, "current_price": 12.0, "today_open": 11.0, "cumulative_volume_lots": 1000}}
    universe = {"2323": {"name": "測試股", "market": "TWSE", "previous_volume_lots": 1000}}
    candidates = runner._dynamic_candidate_gate(raw, universe)

    assert candidates == []
    assert runner._last_dynamic_cooldown_skipped == 1


def test_dynamic_retry_state_round_trips_in_runtime_state(tmp_path):
    runner = TianjiProductionRunner(repo_root=tmp_path, telegram=False)
    runner.trade_date = "2026-10-14"
    runner._set_runtime_path()
    runner.dynamic_retry_after = {"2323": (datetime.now(TAIPEI) + timedelta(minutes=1)).isoformat()}
    runner._save_runtime_state()

    restored = TianjiProductionRunner(repo_root=tmp_path, telegram=False)
    restored.trade_date = runner.trade_date
    restored._load_runtime_state()
    assert restored.dynamic_retry_after == runner.dynamic_retry_after
    runner._fugle_executor.shutdown(wait=False, cancel_futures=True)
    restored._fugle_executor.shutdown(wait=False, cancel_futures=True)
