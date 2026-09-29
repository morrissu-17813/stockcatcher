from datetime import datetime, timezone, timedelta
from pathlib import Path

from tianji_3k.core.trading_session import TradingSession
from tianji_3k.core.process_lock import SingleInstanceLock
from tianji_3k.tools.preflight import run_preflight

TAIPEI = timezone(timedelta(hours=8))


def test_session_phases():
    s = TradingSession()
    d = datetime(2026, 9, 23, 8, 10, tzinfo=TAIPEI)
    assert s.phase(d) == "PREMARKET_WAIT"
    assert s.phase(d.replace(hour=8, minute=30)) == "PREMARKET"
    assert s.phase(d.replace(hour=9, minute=5)) == "RADAR"
    assert s.phase(d.replace(hour=13, minute=31)) == "GROUND_TRUTH"
    assert s.phase(d.replace(hour=13, minute=36)) == "STOP"
    assert s.phase(d.replace(day=26, hour=10)) == "CLOSED"


def test_single_instance_lock_releases(tmp_path: Path):
    p = tmp_path / "runner.lock"
    lock = SingleInstanceLock(p)
    lock.acquire()
    assert p.exists()
    lock.release()
    assert not p.exists()


def test_preflight_has_required_checks(tmp_path: Path):
    result = run_preflight(Path(__file__).resolve().parents[2])
    assert "checks" in result
    assert result["checks"]["runner"] is True
    assert result["checks"]["ledger"] is True
