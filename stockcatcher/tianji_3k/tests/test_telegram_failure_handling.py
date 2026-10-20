from datetime import datetime, timedelta
from types import SimpleNamespace

import requests

from tianji_3k.notification.telegram import TelegramNotifier
from tianji_3k.runner import TAIPEI, TianjiProductionRunner


def test_read_timeout_returns_unknown_without_raising(monkeypatch):
    notifier = TelegramNotifier(token="t", chat_id="c")

    def timeout(*args, **kwargs):
        raise requests.exceptions.ReadTimeout("read timed out")

    monkeypatch.setattr("tianji_3k.notification.telegram.requests.post", timeout)
    result = notifier.send("test")

    assert result["status"] == "UNKNOWN"
    assert result["error_type"] == "ReadTimeout"
    assert result["message_id"] is None


def test_connect_timeout_returns_failed_without_raising(monkeypatch):
    notifier = TelegramNotifier(token="t", chat_id="c")

    def timeout(*args, **kwargs):
        raise requests.exceptions.ConnectTimeout("connect timed out")

    monkeypatch.setattr("tianji_3k.notification.telegram.requests.post", timeout)
    result = notifier.send("test")

    assert result["status"] == "FAILED"
    assert result["error_type"] == "ConnectTimeout"


def test_http_500_is_ambiguous(monkeypatch):
    notifier = TelegramNotifier(token="t", chat_id="c")

    class Response:
        status_code = 500

    monkeypatch.setattr("tianji_3k.notification.telegram.requests.post", lambda *a, **k: Response())
    result = notifier.send("test")
    assert result["status"] == "UNKNOWN"


class FakeLedger:
    def __init__(self, status, latest=None):
        self.status = status
        self.latest = latest or {}
        self.events = []

    def iter_predictions(self, trade_date):
        return [{
            "prediction_id": "p1", "trade_date": trade_date, "symbol": "5340",
            "notification": {"should_send": True},
        }]

    def notification_status(self, trade_date, symbol, prediction_id):
        return self.status

    def events_for_symbol(self, trade_date, symbol):
        return [self.latest] if self.latest else []

    def append_event(self, trade_date, symbol, event):
        self.events.append(event)
        self.status = event.get("notification_status", self.status)


def _bare_runner(status, latest=None):
    runner = object.__new__(TianjiProductionRunner)
    runner.trade_date = "2026-10-20"
    runner.notifier = SimpleNamespace(enabled=True)
    runner.ledger = FakeLedger(status, latest)
    return runner


def test_reconcile_never_resends_unknown_delivery(monkeypatch):
    runner = _bare_runner("UNKNOWN", {"event_type": "NOTIFICATION", "prediction_id": "p1", "notification_status": "UNKNOWN"})
    called = []
    monkeypatch.setattr(runner, "_send_prediction_notification", lambda *a, **k: called.append(True))
    assert runner.reconcile_pending_notifications() == 0
    assert called == []


def test_reconcile_does_not_immediately_retry_failed_send(monkeypatch):
    latest = {
        "event_type": "NOTIFICATION", "prediction_id": "p1", "notification_status": "FAILED",
        "sent_at": datetime.now(TAIPEI).isoformat(),
    }
    runner = _bare_runner("FAILED", latest)
    called = []
    monkeypatch.setattr(runner, "_send_prediction_notification", lambda *a, **k: called.append(True))
    assert runner.reconcile_pending_notifications() == 0
    assert called == []


def test_stale_sending_becomes_unknown_not_resend(monkeypatch):
    old = (datetime.now(TAIPEI) - timedelta(minutes=5)).isoformat()
    latest = {"event_type": "NOTIFICATION", "prediction_id": "p1", "notification_status": "SENDING", "sent_at": old}
    runner = _bare_runner("SENDING", latest)
    runner.notification_events = []
    runner.ledger.append_daily_event = lambda trade_date, event: None
    called = []
    monkeypatch.setattr(runner, "_send_prediction_notification", lambda *a, **k: called.append(True))
    assert runner.reconcile_pending_notifications() == 0
    assert called == []
    assert runner.ledger.events[-1]["notification_status"] == "UNKNOWN"


def test_runner_records_unknown_and_does_not_propagate_notifier_exception():
    runner = _bare_runner(None)
    runner.notification_events = []
    runner.ledger.append_daily_event = lambda trade_date, event: None
    runner.notifier = SimpleNamespace(
        enabled=True,
        send_intraday_prediction=lambda event: (_ for _ in ()).throw(requests.exceptions.ReadTimeout("read timed out")),
    )

    event = {
        "trade_date": runner.trade_date,
        "symbol": "5340",
        "prediction_id": "p1",
        "trigger_snapshot": {"snapshot_id": "s1", "current_price": 102.0, "signal_level": "EARLY"},
        "volume_snapshot": {},
    }
    result = runner._send_prediction_notification(event)
    assert result["status"] == "UNKNOWN"
    assert runner.ledger.status == "UNKNOWN"
    assert [e["notification_status"] for e in runner.ledger.events] == ["SENDING", "UNKNOWN"]

    # A second invocation for the same prediction is suppressed after UNKNOWN.
    again = runner._send_prediction_notification(event)
    assert again["status"] == "UNKNOWN"
    assert again.get("skipped") is True
    assert len(runner.ledger.events) == 2
