from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any, Iterable


class PredictionLedger:
    """Durable append-only ledger for prediction -> validation lifecycle."""

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
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")

    @staticmethod
    def _atomic(path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)

    def write_context(self, context: dict[str, Any]) -> Path:
        p = self._dir(context["trade_date"], context["symbol"]) / "context.json"
        if p.exists():
            return p
        self._atomic(p, context)
        return p

    def create_prediction(self, context, trigger_snapshot, volume_snapshot, notification) -> dict[str, Any]:
        prediction_id = f"{context['trade_date'].replace('-', '')}-{context['symbol']}-{uuid.uuid4().hex[:12]}"
        event = {
            "prediction_id": prediction_id,
            "trade_date": context["trade_date"],
            "symbol": context["symbol"],
            "event_type": "INTRADAY_3K_PREDICTION",
            "created_at": trigger_snapshot.get("observed_at"),
            "context": context,
            "trigger_snapshot": trigger_snapshot,
            "volume_snapshot": volume_snapshot,
            "notification": notification,
            "notification_status": notification.get("status"),
            "immutable": True,
            "schema_version": "prediction-v2.1",
        }
        self._append(self._dir(context["trade_date"], context["symbol"]) / "events.jsonl", event)
        self._append(self.validation_root / "master_prediction_log.jsonl", event)
        return event

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
                out.append(json.loads(line))
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
        events = self.read_jsonl(self._dir(trade_date, symbol) / "events.jsonl")
        for e in events:
            if e.get("event_type") != event_type:
                continue
            if key is None or e.get(key) == value:
                return True
        return False
