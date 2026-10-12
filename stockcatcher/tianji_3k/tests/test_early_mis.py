from datetime import datetime, timedelta, timezone
import time

from tianji_3k.core.snapshot import build_snapshot
from tianji_3k.core.state_machine import IntradayStateMachine
from tianji_3k.core.volume_predictor import IntradayVolumePredictor
from tianji_3k.core.prediction_score import IntradayPredictionScorer
from tianji_3k.runner import TianjiProductionRunner

TAIPEI = timezone(timedelta(hours=8))


class FakeLedger:
    def __init__(self):
        self.predictions = []
        self.events = []

    def iter_predictions(self, trade_date):
        return list(self.predictions)

    def create_prediction(self, context, trigger_snapshot, volume_snapshot, notification):
        event = {
            "prediction_id": "test-prediction", "trade_date": context["trade_date"],
            "symbol": context["symbol"], "event_type": "INTRADAY_3K_PREDICTION",
            "created_at": trigger_snapshot["observed_at"], "context": context,
            "trigger_snapshot": trigger_snapshot, "volume_snapshot": volume_snapshot,
            "notification": notification,
        }
        self.predictions.append(event)
        return event

    def append_event(self, trade_date, symbol, event):
        self.events.append(event)


class FakeNotifier:
    enabled = False


def make_runner():
    runner = object.__new__(TianjiProductionRunner)
    runner.states = {"1234": IntradayStateMachine()}
    runner._latest_snapshot_received_at = {"1234": time.monotonic()}
    runner.volume_predictor = IntradayVolumePredictor()
    runner.prediction_scorer = IntradayPredictionScorer()
    runner.ledger = FakeLedger()
    runner.events = []
    runner.notifier = FakeNotifier()
    runner._record_notification = lambda **kwargs: None
    runner._save_runtime_state = lambda: None
    return runner


def make_snap(volume_lots, identity, observed_at=None):
    observed = (observed_at or datetime.now(TAIPEI)).isoformat()
    return build_snapshot("1234", {
        "observed_at": observed, "current_price": 105.0, "previous_close": 100.0,
        "today_open": 101.0, "cumulative_volume_lots": volume_lots, "up_pct": 5.0,
        "is_traded": True, "data_identity": identity,
    }, name="測試股", market="TWSE")


def context():
    return {
        "trade_date": "2026-10-12", "symbol": "1234", "name": "測試股",
        "breakout_level": 103.0, "k1_high": 103.0, "k2_high": 102.0,
        "vma5_lots": 2000.0, "previous_close": 100.0,
        "ma20": 102.0, "ma60": 98.0, "ma20_prev": 101.0,
    }


def test_mis_early_triggers_without_fugle_when_live_volume_pace_is_high():
    runner = make_runner()
    base = datetime.now(TAIPEI)
    for volume, identity, seconds in [(1500, "id-1", 0), (1550, "id-2", 30), (1600, "id-3", 60)]:
        snap = make_snap(volume, identity, base + timedelta(seconds=seconds))
        runner._latest_snapshot_received_at["1234"] = time.monotonic()
        runner._finalize_mis_early("1234", context(), snap)
    assert len(runner.ledger.predictions) == 1
    prediction = runner.ledger.predictions[0]
    assert prediction["trigger_snapshot"]["signal_level"] == "EARLY"
    assert prediction["trigger_snapshot"]["early_evidence_source"] == "MIS_LIVE"
    assert prediction["trigger_snapshot"]["mis_volume_delta_lots"] == 100.0
    assert prediction["trigger_snapshot"]["mis_live_volume_ratio"] > 1.5
    assert prediction["trigger_snapshot"]["mis_volume_baseline_source"] == "VMA5_DAILY_DIV_54"
    assert prediction["trigger_snapshot"]["fugle_5m_confirmation"] == {}


def test_mis_early_does_not_trigger_without_new_live_volume():
    runner = make_runner()
    base = datetime.now(TAIPEI)
    for identity, seconds in [("id-1", 0), ("id-2", 30), ("id-3", 60)]:
        snap = make_snap(1500, identity, base + timedelta(seconds=seconds))
        runner._latest_snapshot_received_at["1234"] = time.monotonic()
        runner._finalize_mis_early("1234", context(), snap)
    assert runner.ledger.predictions == []
