"""Read-only watcher for Tianji 3K prediction/validation ledgers.

The Lab never writes into the production tree. It discovers new prediction IDs,
keeps a bounded in-memory cursor, and exposes normalized signal summaries for
operator review. Automatic execution must additionally pass the Lab confirmation
chain and requires a verified production event sample/schema mapping.
"""
from __future__ import annotations
import os
from pathlib import Path
from datetime import datetime, timezone, timedelta
from threading import RLock
from typing import Any
from .production_reader import iter_production_events

TAIPEI = timezone(timedelta(hours=8))
HERE = Path(__file__).resolve().parents[1]


def default_source_root() -> Path:
    configured = os.getenv("TIANJI_3K_DATA_ROOT", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    candidates = [
        HERE.parent / "tianji_3k",
        HERE.parent / "stockcatcher" / "tianji_3k",
        HERE.parent.parent / "tianji_3k",
    ]
    for path in candidates:
        if path.is_dir():
            return path.resolve()
    return candidates[0].resolve()


class TianjiSignalFeed:
    def __init__(self, source_root: str | Path | None = None):
        self.source_root = Path(source_root).expanduser().resolve() if source_root else default_source_root()
        self._seen: set[str] = set()
        self._lock = RLock()
        self._latest: list[dict[str, Any]] = []
        self._last_scan_at: str | None = None
        self._last_error: str | None = None

    def scan(self) -> dict[str, Any]:
        at = datetime.now(TAIPEI).isoformat(timespec="seconds")
        if not self.source_root.is_dir():
            with self._lock:
                self._last_scan_at = at
                self._last_error = "找不到 Tianji 3K 資料目錄；請設定 TIANJI_3K_DATA_ROOT"
                self._latest = []
                return self.status()
        try:
            events = list(iter_production_events(self.source_root))
            events.sort(key=lambda e: str(e.get("occurred_at") or ""), reverse=True)
            fresh = []
            with self._lock:
                for event in events:
                    if event.get("event_type") != "prediction.recorded":
                        continue
                    eid = str(event.get("event_id") or "")
                    if not eid or eid in self._seen:
                        continue
                    self._seen.add(eid)
                    payload = event.get("payload") or {}
                    snap = payload.get("trigger_snapshot") or {}
                    note = payload.get("notification") or {}
                    fresh.append({
                        "event_id": eid,
                        "prediction_id": payload.get("prediction_id"),
                        "symbol": str(payload.get("symbol") or ""),
                        "trade_date": payload.get("trade_date"),
                        "occurred_at": event.get("occurred_at"),
                        "notification_status": payload.get("notification_status"),
                        "source_path": payload.get("source_path"),
                        "trigger_snapshot": snap,
                        "notification": note,
                        "read_only": True,
                        "execution_status": "待確認正式訊號欄位與交易映射",
                    })
                self._latest = (fresh + self._latest)[:200]
                self._last_scan_at = at
                self._last_error = None
                return self.status()
        except Exception as exc:
            with self._lock:
                self._last_scan_at = at
                self._last_error = f"{type(exc).__name__}: {exc}"
                return self.status()

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "configured_path": str(self.source_root),
                "path_exists": self.source_root.is_dir(),
                "last_scan_at": self._last_scan_at,
                "last_error": self._last_error,
                "new_signal_count": len(self._latest),
                "signals": [dict(x) for x in self._latest[:50]],
                "mode": "read-only; no production writes; no orders placed by this adapter",
            }
