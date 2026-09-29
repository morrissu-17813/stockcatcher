"""Prediction and ground-truth event logger for Tianji 3K.

Writes append-only JSONL records under the package's logs/ directory by default.
The logger is intentionally dependency-free and failures are isolated from the
trading runner.
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Optional

log = logging.getLogger("tianji_3k.prediction_log")


def _json_default(value: Any):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    return str(value)


class PredictionLogger:
    """Append prediction events and later Ground Truth validation results."""

    def __init__(self, log_dir: Optional[str | Path] = None):
        if log_dir is None:
            # Keep runtime artifacts inside the Tianji package, not the root .env area.
            log_dir = Path(__file__).resolve().parents[1] / "logs"
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, target_date: date) -> Path:
        return self.log_dir / f"prediction_{target_date.isoformat()}.jsonl"

    def _append(self, target_date: date, record: Dict[str, Any]) -> None:
        try:
            path = self._path(target_date)
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False, default=_json_default) + "\n")
        except Exception:
            # Logging must never stop the trading engine.
            log.exception("寫入 Prediction Log 失敗（忽略）。")

    def log_event(
        self,
        target_date: date,
        symbol: str,
        state: str,
        event: Optional[str],
        signal: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._append(target_date, {
            "record_type": "prediction",
            "timestamp": datetime.now().astimezone().isoformat(),
            "date": target_date.isoformat(),
            "symbol": symbol,
            "state": state,
            "event": event,
            "signal": signal or {},
        })

    def log_ground_truth(
        self,
        target_date: date,
        symbol: str,
        state: str,
        event: Optional[str],
        result: Dict[str, Any],
        signal: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._append(target_date, {
            "record_type": "ground_truth",
            "timestamp": datetime.now().astimezone().isoformat(),
            "date": target_date.isoformat(),
            "symbol": symbol,
            "state": state,
            "event": event,
            "prediction_signal": signal or {},
            "ground_truth": result or {},
        })
