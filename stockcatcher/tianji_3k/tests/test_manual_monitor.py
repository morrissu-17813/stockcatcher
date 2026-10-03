from pathlib import Path

from tianji_3k.runner import TianjiProductionRunner


def test_manual_monitor_ignores_session_stop_and_stops_cleanly(tmp_path: Path):
    repo_root = tmp_path / "stockcatcher"
    (repo_root / "tianji_3k" / "predictions").mkdir(parents=True)

    runner = TianjiProductionRunner(repo_root=repo_root, telegram=False)
    runner.process_lock.acquire = lambda: None
    runner.process_lock.release = lambda: None
    runner.session.phase = lambda now=None: "STOP"
    runner._load_pool = lambda: setattr(runner, "pool", [{"symbol": "2330", "name": "台積電"}])

    calls = {"count": 0}

    def fake_poll_once():
        calls["count"] += 1
        raise KeyboardInterrupt

    runner.poll_once = fake_poll_once

    assert runner.run_forever(manual_monitor=True) == 0
    assert calls["count"] == 1


def test_run_forever_manual_mode_is_opt_in_for_noninteractive(tmp_path: Path, monkeypatch):
    # Production --run remains strict in non-interactive environments.
    repo_root = tmp_path / "stockcatcher"
    (repo_root / "tianji_3k" / "predictions").mkdir(parents=True)
    runner = TianjiProductionRunner(repo_root=repo_root, telegram=False)
    runner.session.is_trading_candidate = lambda d: False
    assert runner.run_forever(manual_monitor=False) == 0

