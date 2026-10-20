"""Read-only adapter for Tianji 3K Prediction Ledger JSON/JSONL files.

This module deliberately does not import any production Python module. It reads
only explicitly supplied files/directories and emits normalized Lab events.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Iterator


def _stable_id(source_key: str, row: dict[str, Any]) -> str:
    raw = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(f"{source_key}\n{raw}".encode("utf-8")).hexdigest()[:24]
    return f"prod-ro-{digest}"


def _read_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            for line_no, line in enumerate(f, 1):
                if not line.strip():
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(item, dict):
                    item.setdefault("_source_line", line_no)
                    yield item
    except (OSError, UnicodeError):
        return


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _occurred_at(row: dict[str, Any], trade_date: str | None = None) -> str | None:
    for key in ("created_at", "occurred_at", "validated_at", "observed_at", "timestamp"):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value
    day = str(row.get("trade_date") or trade_date or "")
    if len(day) == 10:
        # Explicit fallback is labelled in payload; no claim this was actual event time.
        return f"{day}T23:59:59+08:00"
    return None


def _normalise_prediction(row: dict[str, Any], source_path: Path, root: Path) -> dict[str, Any] | None:
    if row.get("event_type") != "INTRADAY_3K_PREDICTION":
        return None
    prediction_id = row.get("prediction_id")
    symbol = row.get("symbol")
    occurred_at = _occurred_at(row)
    if not prediction_id or not symbol or not occurred_at:
        return None
    relative = str(source_path.relative_to(root)) if source_path.is_relative_to(root) else source_path.name
    payload = {
        "prediction_id": str(prediction_id),
        "trade_date": row.get("trade_date"),
        "symbol": str(symbol),
        "prediction_type": row.get("event_type"),
        "schema_version": row.get("schema_version"),
        "context": row.get("context", {}),
        "trigger_snapshot": row.get("trigger_snapshot", {}),
        "volume_snapshot": row.get("volume_snapshot", {}),
        "notification": row.get("notification", {}),
        "notification_status": row.get("notification_status"),
        "source_path": relative,
        "source_event_id": str(prediction_id),
        "read_only_import": True,
        "occurred_at_is_fallback": not any(row.get(k) for k in ("created_at", "occurred_at", "observed_at", "timestamp")),
    }
    return {
        "event_id": _stable_id(relative, row),
        "event_type": "prediction.recorded",
        "occurred_at": occurred_at,
        "source": "tianji-3k-readonly",
        "payload": payload,
    }


def _normalise_validation(row: dict[str, Any], source_path: Path, root: Path) -> dict[str, Any] | None:
    event_type = str(row.get("event_type", ""))
    if event_type not in {"PREDICTION_VALIDATION", "prediction.validated", "PREDICTION_VALIDATED"}:
        return None
    prediction_id = row.get("prediction_id")
    symbol = row.get("symbol")
    occurred_at = _occurred_at(row)
    if not prediction_id or not symbol or not occurred_at:
        return None
    relative = str(source_path.relative_to(root)) if source_path.is_relative_to(root) else source_path.name
    payload = dict(row)
    payload.pop("_source_line", None)
    payload.update({"source_path": relative, "read_only_import": True})
    return {
        "event_id": _stable_id(relative, row),
        "event_type": "prediction.validated",
        "occurred_at": occurred_at,
        "source": "tianji-3k-readonly",
        "payload": payload,
    }


def iter_production_events(source_root: str | Path, since: str | None = None) -> Iterator[dict[str, Any]]:
    """Read production ledger files without writing to the source tree.

    Expected root is the tianji_3k data root containing `predictions/` and/or
    `validation/`. Supports per-symbol `events.jsonl`, master prediction logs,
    master validation logs, and per-symbol `ground_truth.json` snapshots.
    """
    root = Path(source_root).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        raise FileNotFoundError(f"Source root does not exist or is not a directory: {root}")

    candidates: list[Path] = []
    predictions_dir = root / "predictions"
    if predictions_dir.is_dir():
        candidates.extend(sorted(predictions_dir.glob("*/*/events.jsonl")))
    validation_dir = root / "validation"
    for name in ("master_prediction_log.jsonl", "master_prediction_validation_log.jsonl", "master_prediction_log.jsonl", "master_ground_truth_log.jsonl"):
        p = validation_dir / name
        if p.is_file() and p not in candidates:
            candidates.append(p)
    # Also accept a direct directory that itself contains prediction date folders.
    candidates.extend(p for p in sorted(root.glob("*/*/events.jsonl")) if p not in candidates)

    seen: set[str] = set()
    for path in candidates:
        for row in _read_jsonl(path):
            event = _normalise_prediction(row, path, root) or _normalise_validation(row, path, root)
            if not event:
                continue
            if since and str(event["occurred_at"])[:10] < since:
                continue
            if event["event_id"] in seen:
                continue
            seen.add(event["event_id"])
            yield event

    # Ground truth snapshots may exist even when validation rows are not present.
    if predictions_dir.is_dir():
        for path in sorted(predictions_dir.glob("*/*/ground_truth.json")):
            row = _read_json(path)
            if not row:
                continue
            day = str(row.get("trade_date") or path.parts[-3])
            if since and day < since:
                continue
            symbol = row.get("symbol") or path.parent.name
            if not symbol or not day:
                continue
            relative = str(path.relative_to(root))
            payload = {**row, "symbol": str(symbol), "trade_date": day, "source_path": relative, "read_only_import": True}
            event = {
                "event_id": _stable_id(relative, row),
                "event_type": "prediction.validated",
                "occurred_at": _occurred_at(row, day),
                "source": "tianji-3k-readonly",
                "payload": payload,
            }
            if event["occurred_at"] and event["event_id"] not in seen:
                seen.add(event["event_id"])
                yield event


