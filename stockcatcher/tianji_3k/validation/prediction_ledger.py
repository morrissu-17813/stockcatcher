from __future__ import annotations

import hashlib
import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


_LEDGER_LOCK = threading.RLock()


class PredictionLedger:
    """Append-only prediction ledger with per-symbol files as canonical records.

    The master prediction log is a rebuildable index. Prediction events are never
    edited in place; lifecycle updates must be appended as separate events linked
    by prediction_id.
    """

    SCHEMA_VERSION = "prediction-v2.2"

    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.validation_root = self.root.parent / "validation"
        self.validation_root.mkdir(parents=True, exist_ok=True)

    def _dir(self, trade_date: str, symbol: str) -> Path:
        p = self.root / str(trade_date) / str(symbol)
        p.mkdir(parents=True, exist_ok=True)
        return p

    @staticmethod
    def _append(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
        # A process-wide lock prevents interleaved writes from concurrent Radar
        # workers in this process. Production's existing process lock prevents
        # a second runner instance from writing the same ledger concurrently.
        with _LEDGER_LOCK:
            with path.open("a", encoding="utf-8", newline="") as f:
                f.write(line)
                f.flush()
                os.fsync(f.fileno())

    @staticmethod
    def _atomic(path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)

    @staticmethod
    def _safe_float(value: Any) -> float | None:
        try:
            if value is None or value == "":
                return None
            number = float(value)
            return number if number == number and abs(number) != float("inf") else None
        except (TypeError, ValueError):
            return None

    @classmethod
    def _normalized_signal(cls, context: dict[str, Any], trigger: dict[str, Any], volume: dict[str, Any]) -> dict[str, Any]:
        """Stable, query-friendly projection; raw source objects remain intact."""
        return {
            "signal_level": trigger.get("signal_level") or volume.get("signal_level") or "UNKNOWN",
            "signal_time": trigger.get("observed_at") or trigger.get("timestamp"),
            "signal_price": cls._safe_float(trigger.get("current_price") or trigger.get("price")),
            "breakout_base": cls._safe_float(context.get("breakout_level") or context.get("breakout_base")),
            "extension_pct": cls._safe_float(trigger.get("extension_pct") or trigger.get("up_pct")),
            "up_pct": cls._safe_float(trigger.get("up_pct")),
            "projected_volume_ratio": cls._safe_float(volume.get("projected_ratio")),
            "live_volume_ratio": cls._safe_float(volume.get("live_volume_ratio")),
            "cumulative_volume_lots": cls._safe_float(volume.get("cumulative_volume_lots")),
            "vma5_lots": cls._safe_float(volume.get("vma5_lots")),
            "prediction_score": cls._safe_float(trigger.get("prediction_score")),
            "evidence_source": trigger.get("early_evidence_source") or volume.get("early_evidence_source"),
            "snapshot_id": trigger.get("snapshot_id"),
            "stage0_pass": context.get("stage0_pass"),
            "stage1_pass": context.get("stage1_pass"),
            "stage2_pass": context.get("stage2_pass"),
            "stage3_pass": context.get("stage3_pass"),
            "final_pool": context.get("final_pool"),
            "dynamic_candidate": context.get("dynamic_candidate"),
        }

    @staticmethod
    def _record_hash(event: dict[str, Any]) -> str:
        material = {k: v for k, v in event.items() if k not in {"record_hash"}}
        raw = json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def write_context(self, context: dict[str, Any]) -> Path:
        p = self._dir(context["trade_date"], context["symbol"]) / "context.json"
        if p.exists():
            return p
        self._atomic(p, context)
        return p

    def create_prediction(self, context, trigger_snapshot, volume_snapshot, notification) -> dict[str, Any]:
        trade_date = str(context["trade_date"])
        symbol = str(context["symbol"])
        snapshot_id = trigger_snapshot.get("snapshot_id")
        # Idempotency at the ledger boundary: callers need not implement a
        # separate check-then-write sequence for a repeated snapshot.
        if snapshot_id:
            existing = self.find_prediction_by_snapshot(trade_date, symbol, str(snapshot_id))
            if existing is not None:
                # Some historical/test producers reuse a snapshot label across
                # distinct observation times. Treat only the same identity AND
                # timestamp as an idempotent retry.
                same_observation = (
                    existing.get("trigger_snapshot", {}).get("observed_at")
                    == trigger_snapshot.get("observed_at")
                )
                if same_observation:
                    self._ensure_master_record(existing)
                    return existing

        now = datetime.now(timezone.utc).isoformat()
        event = {
            "prediction_id": f"{trade_date.replace('-', '')}-{symbol}-{uuid.uuid4().hex[:12]}",
            "event_id": uuid.uuid4().hex,
            "trade_date": trade_date,
            "symbol": symbol,
            "event_type": "INTRADAY_3K_PREDICTION",
            "created_at": trigger_snapshot.get("observed_at") or now,
            "recorded_at": now,
            "context": context,
            "trigger_snapshot": trigger_snapshot,
            "volume_snapshot": volume_snapshot,
            "signal": self._normalized_signal(context, trigger_snapshot, volume_snapshot),
            "notification": notification,
            "notification_status": notification.get("status"),
            "source": {
                "strategy": "TIANJI_3K",
                "signal_origin": "DYNAMIC_CANDIDATE" if context.get("dynamic_candidate") else "FORMAL_3K",
                "snapshot_id": snapshot_id,
            },
            "immutable": True,
            "schema_version": self.SCHEMA_VERSION,
        }
        event["record_hash"] = self._record_hash(event)

        # Per-symbol event file is canonical. Master log is a rebuildable index;
        # if the second append fails, audit/rebuild can repair it without losing
        # the source prediction.
        self._append(self._dir(trade_date, symbol) / "events.jsonl", event)
        self._ensure_master_record(event)
        return event

    def _ensure_master_record(self, event: dict[str, Any]) -> None:
        master = self.validation_root / "master_prediction_log.jsonl"
        with _LEDGER_LOCK:
            existing = self.read_jsonl(master)
            pid = event.get("prediction_id")
            if any(x.get("prediction_id") == pid for x in existing):
                return
            self._append(master, event)

    def append_event(self, trade_date, symbol, event):
        self._append(self._dir(trade_date, symbol) / "events.jsonl", event)

    def write_ground_truth(self, trade_date, symbol, ground_truth):
        p = self._dir(trade_date, symbol) / "ground_truth.json"
        self._atomic(p, ground_truth)
        # Idempotent master log: one latest GT record per symbol/day.
        master = self.validation_root / "master_ground_truth_log.jsonl"
        existing = [x for x in self.read_jsonl(master) if not (str(x.get("trade_date")) == str(trade_date) and str(x.get("symbol")) == str(symbol))]
        existing.append(ground_truth)
        tmp = master.with_suffix(master.suffix + ".tmp")
        tmp.write_text("".join(json.dumps(x, ensure_ascii=False, separators=(",", ":")) + "\n" for x in existing), encoding="utf-8")
        tmp.replace(master)
        return p

    def append_daily_event(self, trade_date, event):
        self._append(self.validation_root / "daily_events" / f"{trade_date}.jsonl", event)

    @staticmethod
    def read_jsonl(path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        out = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                value = json.loads(line)
                if isinstance(value, dict):
                    out.append(value)
            except json.JSONDecodeError:
                continue
        return out

    def iter_predictions(self, trade_date: str) -> Iterable[dict[str, Any]]:
        day = self.root / str(trade_date)
        if not day.exists():
            return []
        out = []
        for p in sorted(day.glob("*/events.jsonl")):
            for e in self.read_jsonl(p):
                if e.get("event_type") == "INTRADAY_3K_PREDICTION":
                    out.append(e)
        return out

    def find_prediction_by_snapshot(self, trade_date: str, symbol: str, snapshot_id: str) -> dict[str, Any] | None:
        for e in self.read_jsonl(self._dir(trade_date, symbol) / "events.jsonl"):
            if e.get("event_type") == "INTRADAY_3K_PREDICTION" and e.get("trigger_snapshot", {}).get("snapshot_id") == snapshot_id:
                return e
        return None

    def events_for_symbol(self, trade_date: str, symbol: str) -> list[dict[str, Any]]:
        return self.read_jsonl(self._dir(trade_date, symbol) / "events.jsonl")

    def notification_status(self, trade_date: str, symbol: str, prediction_id: str) -> str | None:
        status = None
        for e in self.events_for_symbol(trade_date, symbol):
            if e.get("prediction_id") != prediction_id:
                continue
            if e.get("event_type") in {"NOTIFICATION", "INTRADAY_3K_PREDICTION_NOTIFICATION"}:
                status = e.get("notification_status") or e.get("status") or status
        return status

    def prediction_by_id(self, trade_date: str, symbol: str, prediction_id: str) -> dict[str, Any] | None:
        for e in self.events_for_symbol(trade_date, symbol):
            if e.get("event_type") == "INTRADAY_3K_PREDICTION" and e.get("prediction_id") == prediction_id:
                return e
        return None

    def has_event(self, trade_date: str, symbol: str, event_type: str, key: str | None = None, value: Any = None) -> bool:
        for e in self.events_for_symbol(trade_date, symbol):
            if e.get("event_type") != event_type:
                continue
            if key is None or e.get(key) == value:
                return True
        return False

    def audit(self, trade_date: str | None = None) -> dict[str, Any]:
        """Read-only integrity report; malformed JSONL lines are counted, not hidden."""
        files = sorted(self.root.glob("**/events.jsonl")) if trade_date is None else sorted((self.root / str(trade_date)).glob("*/events.jsonl"))
        predictions: dict[str, dict[str, Any]] = {}
        malformed_lines = 0
        event_count = 0
        duplicate_ids: list[str] = []
        hash_mismatches: list[str] = []
        for path in files:
            for raw in path.read_text(encoding="utf-8").splitlines():
                if not raw.strip():
                    continue
                try:
                    event = json.loads(raw)
                    if not isinstance(event, dict):
                        raise ValueError("event_not_object")
                except (json.JSONDecodeError, ValueError):
                    malformed_lines += 1
                    continue
                event_count += 1
                if event.get("event_type") != "INTRADAY_3K_PREDICTION":
                    continue
                pid = str(event.get("prediction_id") or "")
                if not pid:
                    hash_mismatches.append(f"missing_prediction_id:{path}")
                    continue
                if pid in predictions:
                    duplicate_ids.append(pid)
                predictions[pid] = event
                expected = event.get("record_hash")
                if expected and expected != self._record_hash(event):
                    hash_mismatches.append(pid)
        master = self.validation_root / "master_prediction_log.jsonl"
        master_ids = {str(x.get("prediction_id")) for x in self.read_jsonl(master) if x.get("prediction_id")}
        canonical_ids = set(predictions)
        return {
            "trade_date": str(trade_date) if trade_date else None,
            "event_file_count": len(files),
            "event_count": event_count,
            "prediction_count": len(predictions),
            "duplicate_prediction_ids": sorted(set(duplicate_ids)),
            "malformed_jsonl_lines": malformed_lines,
            "record_hash_mismatches": sorted(set(hash_mismatches)),
            "master_missing_prediction_ids": sorted(canonical_ids - master_ids),
            "master_orphan_prediction_ids": sorted(master_ids - canonical_ids),
            "integrity_ok": not (duplicate_ids or malformed_lines or hash_mismatches or canonical_ids != master_ids),
        }

    def rebuild_master_prediction_log(self) -> dict[str, Any]:
        """Rebuild master index from canonical per-symbol immutable prediction events."""
        events = []
        seen = set()
        duplicates = []
        for path in sorted(self.root.glob("**/events.jsonl")):
            for event in self.read_jsonl(path):
                if event.get("event_type") != "INTRADAY_3K_PREDICTION":
                    continue
                pid = event.get("prediction_id")
                if not pid:
                    continue
                if pid in seen:
                    duplicates.append(str(pid))
                    continue
                seen.add(pid)
                events.append(event)
        events.sort(key=lambda x: (str(x.get("trade_date", "")), str(x.get("created_at", "")), str(x.get("prediction_id", ""))))
        master = self.validation_root / "master_prediction_log.jsonl"
        tmp = master.with_suffix(master.suffix + ".tmp")
        tmp.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text("".join(json.dumps(x, ensure_ascii=False, separators=(",", ":")) + "\n" for x in events), encoding="utf-8")
        os.replace(tmp, master)
        return {"rebuilt_count": len(events), "duplicate_prediction_ids": sorted(set(duplicates)), "path": str(master)}
