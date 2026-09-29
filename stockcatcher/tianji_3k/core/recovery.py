from __future__ import annotations

import json
import os
import socket
import time
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

TAIPEI = timezone(timedelta(hours=8))


@dataclass
class RecoveryCheckpoint:
    schema_version: str = "recovery-v1"
    trade_date: str = ""
    phase: str = "INIT"
    last_poll_at: str | None = None
    last_success_at: str | None = None
    poll_sequence: int = 0
    last_error: dict[str, Any] | None = None
    pid: int = os.getpid()
    host: str = socket.gethostname()
    started_at: str | None = None
    updated_at: str | None = None
    clean_shutdown: bool = False

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


class RecoveryManager:
    """Crash-safe checkpoint/heartbeat manager.

    The checkpoint is operational state only; the Prediction Ledger remains the
    source of truth for predictions/events. Atomic replace prevents a torn JSON
    file after process termination.
    """

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.checkpoint = self._load() or RecoveryCheckpoint()

    def _load(self) -> RecoveryCheckpoint | None:
        if not self.path.exists():
            return None
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            allowed = {f for f in RecoveryCheckpoint.__dataclass_fields__}
            data = {k: v for k, v in data.items() if k in allowed}
            return RecoveryCheckpoint(**data)
        except (OSError, ValueError, TypeError):
            return None

    def save(self) -> None:
        self.checkpoint.updated_at = datetime.now(TAIPEI).isoformat()
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(self.checkpoint.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def start(self, trade_date: str, phase: str = "STARTING") -> None:
        self.checkpoint.trade_date = trade_date
        self.checkpoint.phase = phase
        self.checkpoint.started_at = self.checkpoint.started_at or datetime.now(TAIPEI).isoformat()
        self.checkpoint.clean_shutdown = False
        self.checkpoint.pid = os.getpid()
        self.checkpoint.host = socket.gethostname()
        self.save()

    def heartbeat(self, phase: str, success: bool = True, error: dict[str, Any] | None = None) -> None:
        now = datetime.now(TAIPEI).isoformat()
        self.checkpoint.phase = phase
        self.checkpoint.last_poll_at = now
        if success:
            self.checkpoint.last_success_at = now
            self.checkpoint.last_error = None
        else:
            self.checkpoint.last_error = error
        self.checkpoint.poll_sequence += 1
        self.save()

    def mark_clean_shutdown(self) -> None:
        self.checkpoint.phase = "STOPPED"
        self.checkpoint.clean_shutdown = True
        self.save()

    def recovery_needed(self, stale_seconds: int = 120) -> bool:
        c = self.checkpoint
        if not c.trade_date or c.clean_shutdown:
            return False
        if c.phase == "STOPPED":
            return False
        if not c.last_poll_at:
            return True
        try:
            ts = datetime.fromisoformat(c.last_poll_at)
            return (datetime.now(TAIPEI) - ts).total_seconds() >= stale_seconds
        except ValueError:
            return True

    def status(self) -> dict[str, Any]:
        return self.checkpoint.to_dict()
