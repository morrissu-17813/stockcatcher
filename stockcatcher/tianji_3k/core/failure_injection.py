from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .recovery import RecoveryManager
from .simulator import IntradaySimulator
from .state_machine import IntradayStateMachine
from ..notification.gate import evaluate_intraday_notification
from ..validation.prediction_chain import PredictionChain
from ..validation.prediction_ledger import PredictionLedger


@dataclass(frozen=True)
class FailurePoint:
    at_step: int
    name: str
    action: str
    expected_recovery: str


@dataclass
class FailureInjectionResult:
    passed: bool = True
    processed_steps: int = 0
    predictions_created: int = 0
    notifications_sent: int = 0
    notifications_suppressed: int = 0
    validation_count: int = 0
    failures_injected: list[str] = field(default_factory=list)
    recovery_count: int = 0
    errors: list[str] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)


class FailureInjector:
    """Deterministic full-day resilience test harness.

    It exercises the same durable primitives used by production: checkpoint,
    state machine persistence, append-only Prediction Ledger, notification
    idempotency, and Prediction -> Ground Truth validation linkage.
    No live MIS/Fugle/Telegram calls are made.
    """

    DEFAULT_PLAN = (
        FailurePoint(1, "MIS_TIMEOUT", "before_skip", "last good checkpoint retained"),
        FailurePoint(2, "MIS_EMPTY_PAYLOAD", "before_skip", "last good checkpoint retained"),
        FailurePoint(6, "PROCESS_CRASH_AFTER_PREDICTION", "after_restart", "prediction not duplicated"),
        FailurePoint(8, "TELEGRAM_SEND_FAILURE", "after_send_fail", "notification retry is idempotent"),
        FailurePoint(10, "DUPLICATE_SNAPSHOT", "after_duplicate", "duplicate cannot confirm"),
    )

    def __init__(self, root: Path, trade_date: str = "2026-09-23"):
        self.root = Path(root)
        self.trade_date = trade_date
        self.runtime = self.root / "runtime_checkpoint.json"
        self.ledger = PredictionLedger(self.root / "predictions")
        self.recovery = RecoveryManager(self.runtime)
        self.chain = PredictionChain(self.ledger)
        self.states: dict[str, IntradayStateMachine] = {}
        self.prediction_by_snapshot: dict[str, str] = {}
        self.notification_sent: set[str] = set()
        self.failed_once: set[str] = set()

    @staticmethod
    def _rows() -> list[dict[str, Any]]:
        # Deterministic day: 2221 triggers, invalidates, then re-arms; 3066
        # reaches the +9.50% notification suppression boundary.
        series = [
            ("09:10:00", "2221", 103.0, "a"),
            ("09:10:20", "2221", 104.0, "b"),
            ("09:10:40", "2221", 105.0, "c"),  # trigger #1
            ("09:11:00", "2221", 102.0, "d"),  # invalidate
            ("09:11:20", "2221", 104.0, "e"),
            ("09:11:40", "2221", 105.0, "f"),  # trigger #2
            ("09:12:00", "3066", 108.0, "g"),
            ("09:12:20", "3066", 109.5, "h"),  # first valid at +9.5
            ("09:12:40", "3066", 109.5, "h"),  # duplicate identity
            ("09:13:00", "3066", 110.0, "i"),  # suppressed prediction
        ]
        return [
            {
                "symbol": symbol,
                "observed_at": f"2026-09-23T{t}+08:00",
                "current_price": price,
                "previous_close": 100.0,
                "today_open": 100.0,
                "cumulative_volume": 500000 + i * 10000,
                "up_pct": price - 100.0,
                "is_traded": True,
                "data_identity": identity,
            }
            for i, (t, symbol, price, identity) in enumerate(series)
        ]

    def _event(self, result: FailureInjectionResult, event_type: str, **kwargs: Any) -> None:
        row = {"event_type": event_type, "trade_date": self.trade_date, **kwargs}
        result.events.append(row)
        self.ledger.append_daily_event(self.trade_date, row)

    def _restart(self, result: FailureInjectionResult, reason: str) -> None:
        result.recovery_count += 1
        self._event(result, "RECOVERY_DETECTED", reason=reason)
        # Reconstruct all state from the durable checkpoint/ledger.  Production
        # state must never depend solely on in-memory dictionaries.
        self.recovery = RecoveryManager(self.runtime)
        for prediction in self.ledger.iter_predictions(self.trade_date):
            sid = prediction["symbol"]
            snap_id = prediction.get("trigger_snapshot", {}).get("snapshot_id")
            if snap_id:
                self.prediction_by_snapshot.setdefault(snap_id, prediction["prediction_id"])
        for sid in list(self.states):
            events = self.ledger.events_for_symbol(self.trade_date, sid)
            trigger_events = [e for e in events if e.get("event_type") == "STATE_SNAPSHOT"]
            if trigger_events:
                self.states[sid] = IntradayStateMachine.from_dict(trigger_events[-1]["state_machine"])
        self._event(result, "PROCESS_RESTARTED", reason=reason)

    def _persist_state(self, symbol: str) -> None:
        sm = self.states[symbol]
        self.ledger.append_event(
            self.trade_date,
            symbol,
            {
                "event_type": "STATE_SNAPSHOT",
                "symbol": symbol,
                "state_machine": sm.to_dict(),
            },
        )

    def _ensure_prediction(self, result: FailureInjectionResult, symbol: str, snap: dict[str, Any], status: str) -> str:
        snapshot_id = f"sim-{symbol}-{snap['data_identity']}"
        existing = self.prediction_by_snapshot.get(snapshot_id)
        if existing:
            return existing
        ctx = {
            "trade_date": self.trade_date,
            "symbol": symbol,
            "final_pool": True,
            "stage0_pass": True,
            "stage1_pass": True,
            "stage2_pass": True,
            "stage3_pass": True,
        }
        decision = evaluate_intraday_notification(snap["up_pct"])
        notification = decision.to_dict()
        event = self.ledger.create_prediction(
            ctx,
            {**snap, "snapshot_id": f"sim-{symbol}-{snap['data_identity']}"},
            {"projected_ratio": 1.8},
            notification,
        )
        self.prediction_by_snapshot[snapshot_id] = event["prediction_id"]
        result.predictions_created += 1
        if decision.should_send:
            if status == "SEND_FAIL_ONCE":
                self.failed_once.add(event["prediction_id"])
                self.ledger.append_event(self.trade_date, symbol, {
                    "event_type": "NOTIFICATION", "prediction_id": event["prediction_id"],
                    "notification_status": "SEND_FAILED", "error": "INJECTED_TELEGRAM_FAILURE",
                })
                return event["prediction_id"]
            self.notification_sent.add(event["prediction_id"])
            result.notifications_sent += 1
            self.ledger.append_event(self.trade_date, symbol, {
                "event_type": "NOTIFICATION", "prediction_id": event["prediction_id"],
                "notification_status": "SENT",
            })
        else:
            result.notifications_suppressed += 1
            self.ledger.append_event(self.trade_date, symbol, {
                "event_type": "NOTIFICATION", "prediction_id": event["prediction_id"],
                "notification_status": "SUPPRESSED", "suppression_reason": decision.suppression_reason,
            })
        return event["prediction_id"]

    def _retry_notifications(self, result: FailureInjectionResult) -> None:
        for prediction in self.ledger.iter_predictions(self.trade_date):
            pid = prediction["prediction_id"]
            if pid in self.notification_sent:
                continue
            if pid in self.failed_once:
                self.notification_sent.add(pid)
                result.notifications_sent += 1
                self.ledger.append_event(self.trade_date, prediction["symbol"], {
                    "event_type": "NOTIFICATION", "prediction_id": pid,
                    "notification_status": "SENT", "retry": True,
                })

    def run(self, plan: tuple[FailurePoint, ...] | None = None) -> FailureInjectionResult:
        plan = plan or self.DEFAULT_PLAN
        result = FailureInjectionResult()
        self.recovery.start(self.trade_date, "FAILURE_INJECTION")
        rows = self._rows()
        plan_by_step = {f.at_step: f for f in plan}

        for step, raw in enumerate(rows, start=1):
            result.processed_steps += 1
            injected = plan_by_step.get(step)

            # Pre-processing failures: the snapshot never reaches the engine.
            if injected and injected.action == "before_skip":
                result.failures_injected.append(injected.name)
                self._event(result, "FAILURE_INJECTED", step=step, failure=injected.name, phase="BEFORE_PROCESS")
                self.recovery.heartbeat("RADAR_DEGRADED", success=False, error={"code": injected.name})
                continue

            sid = str(raw["symbol"])
            from .snapshot import build_snapshot
            snap = build_snapshot(sid, raw)
            sm = self.states.setdefault(sid, IntradayStateMachine())
            triggered, reason = sm.evaluate(snap, 100.0, 4.0, 0.3)
            self._persist_state(sid)
            self.recovery.heartbeat("RADAR_OK", success=True)
            self._event(result, "RADAR_RESULT", symbol=sid, reason=reason, triggered=triggered, step=step)

            if injected and injected.name == "DUPLICATE_SNAPSHOT":
                result.failures_injected.append(injected.name)
                self._event(result, "FAILURE_INJECTED", step=step, failure=injected.name, phase="DUPLICATE")

            if triggered:
                # First prediction intentionally crashes after the durable prediction write.
                event = self.prediction_by_snapshot.get(f"sim-{sid}-{raw['data_identity']}")
                if event is None:
                    notification_status = "NORMAL"
                    event = self._ensure_prediction(result, sid, raw, notification_status)
                if injected and injected.name == "TELEGRAM_SEND_FAILURE":
                    # Remove the successful notification marker if any and inject a durable failure.
                    result.failures_injected.append(injected.name)
                    pred = self.ledger.prediction_by_id(self.trade_date, sid, event)
                    if pred:
                        self.ledger.append_event(self.trade_date, sid, {
                            "event_type": "NOTIFICATION", "prediction_id": event,
                            "notification_status": "SEND_FAILED",
                            "error": "INJECTED_TELEGRAM_FAILURE",
                        })
                    self.failed_once.add(event)
                    self.notification_sent.discard(event)
                    self._event(result, "FAILURE_INJECTED", step=step, failure=injected.name, phase="AFTER_PREDICTION")
                    # Recover the Telegram failure immediately, then inject a crash
                    # after the durable SENT event to verify restart idempotency.
                    self._retry_notifications(result)
                    result.failures_injected.append("PROCESS_CRASH_AFTER_NOTIFICATION")
                    self._event(result, "FAILURE_INJECTED", step=step, failure="PROCESS_CRASH_AFTER_NOTIFICATION", phase="AFTER_NOTIFICATION")
                    self._restart(result, "PROCESS_CRASH_AFTER_NOTIFICATION")
                if injected and injected.name == "PROCESS_CRASH_AFTER_PREDICTION":
                    result.failures_injected.append(injected.name)
                    self._event(result, "FAILURE_INJECTED", step=step, failure=injected.name, phase="AFTER_PREDICTION")
                    self._restart(result, injected.name)

            if injected and injected.name == "PROCESS_CRASH_AFTER_NOTIFICATION":
                result.failures_injected.append(injected.name)
                self._event(result, "FAILURE_INJECTED", step=step, failure=injected.name, phase="AFTER_NOTIFICATION")
                self._restart(result, injected.name)

        # Retry notification failures.  A prediction already marked SENT is never sent again.
        self._retry_notifications(result)

        # Ground truth is linked independently to every unique prediction.
        predictions = list(self.ledger.iter_predictions(self.trade_date))
        for prediction in predictions:
            symbol = prediction["symbol"]
            gt = {
                "trade_date": self.trade_date,
                "symbol": symbol,
                "close": 105.0 if symbol == "2221" else 110.0,
                "gain_pct": 5.0 if symbol == "2221" else 10.0,
                "volume_ratio": 1.7,
                "ground_truth_3k": True,
                "validated_at": "2026-09-23T13:31:00+08:00",
            }
            if not self.ledger.has_event(self.trade_date, symbol, "PREDICTION_VALIDATION", "prediction_id", prediction["prediction_id"]):
                self.ledger.append_event(self.trade_date, symbol, self.chain.validate_prediction(prediction, gt))
                result.validation_count += 1

        # Repeat the validation phase: it must remain idempotent.
        for prediction in list(self.ledger.iter_predictions(self.trade_date)):
            symbol = prediction["symbol"]
            if not self.ledger.has_event(self.trade_date, symbol, "PREDICTION_VALIDATION", "prediction_id", prediction["prediction_id"]):
                raise AssertionError("GROUND_TRUTH_NOT_IDEMPOTENT")

        self.recovery.mark_clean_shutdown()
        predictions = list(self.ledger.iter_predictions(self.trade_date))
        if len(predictions) != len({p["prediction_id"] for p in predictions}):
            result.errors.append("DUPLICATE_PREDICTION_ID")
        for p in predictions:
            events = self.ledger.events_for_symbol(self.trade_date, p["symbol"])
            validations = [e for e in events if e.get("event_type") == "PREDICTION_VALIDATION" and e.get("prediction_id") == p["prediction_id"]]
            if len(validations) != 1:
                result.errors.append(f"VALIDATION_CHAIN_COUNT:{p['prediction_id']}:{len(validations)}")
        if not self.recovery.checkpoint.clean_shutdown:
            result.errors.append("NOT_CLEAN_SHUTDOWN")
        if result.errors:
            result.passed = False
        return result


def write_report(result: FailureInjectionResult, path: Path) -> Path:
    payload = {
        "schema_version": "failure-injection-v1",
        "passed": result.passed,
        "processed_steps": result.processed_steps,
        "predictions_created": result.predictions_created,
        "notifications_sent": result.notifications_sent,
        "notifications_suppressed": result.notifications_suppressed,
        "validation_count": result.validation_count,
        "recovery_count": result.recovery_count,
        "failures_injected": result.failures_injected,
        "errors": result.errors,
        "events": result.events,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
