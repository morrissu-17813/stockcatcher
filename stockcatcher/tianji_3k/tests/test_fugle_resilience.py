from types import SimpleNamespace

import pytest

from tianji_3k.data.fugle import FugleAPIError, FugleProvider


def test_fugle_401_is_structured_error(monkeypatch):
    provider = FugleProvider("valid-looking-key")

    def fake_get(*args, **kwargs):
        response = SimpleNamespace(status_code=401)
        err = __import__("requests").HTTPError("401 unauthorized", response=response)
        raise err

    monkeypatch.setattr("tianji_3k.data.fugle.requests.get", fake_get)
    with pytest.raises(FugleAPIError) as exc:
        provider.get_5m_bars("2330")
    assert exc.value.status_code == 401
    assert exc.value.symbol == "2330"


def test_fugle_health_check_accepts_http_success_without_23_bars(monkeypatch):
    provider = FugleProvider("key")
    monkeypatch.setattr(provider, "get_5m_bars", lambda symbol: [{"date": "x"}] * 3)
    result = provider.check_5m_access("2330")
    assert result == {"ok": True, "status": "OK", "symbol": "2330", "bars": 3}


def test_runner_timestamp_normalization_accepts_snapshot_string():
    from datetime import datetime
    from tianji_3k.runner import TianjiProductionRunner, TAIPEI

    value = "2026-10-06T10:30:00+08:00"
    assert TianjiProductionRunner._iso_timestamp(value) == value
    dt = TianjiProductionRunner._as_datetime(value)
    assert isinstance(dt, datetime)
    assert dt.tzinfo == TAIPEI


def test_runner_timestamp_normalization_accepts_datetime():
    from datetime import datetime
    from tianji_3k.runner import TianjiProductionRunner, TAIPEI

    dt = datetime(2026, 10, 6, 10, 30, tzinfo=TAIPEI)
    assert TianjiProductionRunner._iso_timestamp(dt) == dt.isoformat()
    assert TianjiProductionRunner._as_datetime(dt) == dt


def test_runner_trigger_reaches_fugle_and_prediction(tmp_path, monkeypatch):
    from tianji_3k.runner import TianjiProductionRunner
    from tianji_3k.core.state_machine import IntradayStateMachine

    runner = TianjiProductionRunner(repo_root=tmp_path, telegram=False)
    runner.trade_date = "2026-10-06"
    runner._set_runtime_path()
    runner.pool = [{"symbol": "2330", "name": "台積電", "market": "TWSE"}]
    runner.contexts = {
        "2330": {
            "trade_date": runner.trade_date,
            "symbol": "2330",
            "name": "台積電",
            "market": "TWSE",
            "breakout_level": 100.0,
            "k1_high": 99.0,
            "k2_high": 100.0,
            "vma5_lots": 1000.0,
            "previous_close": 96.0,
            "today_open": 96.0,
        }
    }
    runner.states = {"2330": IntradayStateMachine()}
    runner.dynamic_contexts = {}
    runner.dynamic_attempts = {}
    runner.universe_cache = {"2330": {"symbol": "2330", "name": "台積電", "market": "TWSE", "previous_volume_lots": 5000}}
    runner._premarket_built = True
    runner._fugle_health_checked = False
    runner._fugle_pending = {}

    class FakeMIS:
        def __init__(self):
            self.n = 0
        def fetch_batch(self):
            self.n += 1
            return {
                "2330": {
                    "symbol": "2330",
                    "current_price": 101.0,
                    "previous_close": 96.0,
                    "today_open": 96.0,
                    "cumulative_volume_lots": 3000.0,
                    "cumulative_volume_shares": 3000000.0,
                    "up_pct": 5.2083,
                    "is_traded": True,
                    "data_identity": f"mis-{self.n}",
                    "observed_at": "2026-10-06T10:00:00+08:00",
                }
            }

    class FakeFugle:
        def __init__(self):
            self.health_calls = 0
            self.micro_calls = 0
        def check_5m_access(self, symbol):
            self.health_calls += 1
            return {"ok": True, "status": "OK", "symbol": symbol, "bars": 24}
        def evaluate_3k_micro_breakout(self, symbol):
            self.micro_calls += 1
            return {
                "bar_time": "2026-10-06T09:55:00+08:00",
                "breakout_price": 100.5,
                "close": 101.0,
                "volume": 1300.0,
                "volume_ratio": 1.5,
                "required_volume": 866.7,
                "ma20": 99.0,
                "stop_price": 98.0,
                "bars_used": 23,
            }

    runner.mis_provider = FakeMIS()
    runner.fugle_provider = FakeFugle()
    monkeypatch.setattr(runner, "_dynamic_candidate_gate", lambda raw, universe: [])
    monkeypatch.setattr(runner, "_enrich_dynamic_candidates", lambda candidates: 0)
    monkeypatch.setattr(runner, "_print_radar_monitor", lambda raw, rows: None)
    monkeypatch.setattr(runner, "_radar_rows", lambda: runner.pool)
    monkeypatch.setattr(runner, "_save_runtime_state", lambda: None)
    monkeypatch.setattr(runner.recovery, "heartbeat", lambda *args, **kwargs: None)
    monkeypatch.setattr(runner.recovery_ledger, "append", lambda *args, **kwargs: None)

    runner.poll_once()
    assert runner.fugle_provider.micro_calls == 0

    runner.poll_once()
    assert runner.fugle_provider.health_calls == 1
    assert runner.fugle_provider.micro_calls == 1
    predictions = list(runner.ledger.iter_predictions(runner.trade_date))
    assert len(predictions) == 1
    assert predictions[0]["symbol"] == "2330"
