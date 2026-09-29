from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from .snapshot import build_snapshot
from .state_machine import IntradayStateMachine


@dataclass
class SimulationResult:
    processed: int = 0
    triggers: int = 0
    reasons: dict[str, int] = field(default_factory=dict)
    states: list[dict[str, Any]] = field(default_factory=list)

    def add_reason(self, reason: str) -> None:
        self.reasons[reason] = self.reasons.get(reason, 0) + 1


class IntradaySimulator:
    """Deterministic replay harness for MIS snapshots.

    Input is JSON array or JSONL. It intentionally uses the same snapshot and
    state-machine path as production so tests can exercise crash/restart and
    rearm semantics without touching live MIS or Telegram.
    """

    def __init__(self, breakout_levels: dict[str, float], buffer_pct: float = 0.3):
        self.breakout_levels = {str(k): float(v) for k, v in breakout_levels.items()}
        self.buffer_pct = buffer_pct
        self.states: dict[str, IntradayStateMachine] = {}

    @staticmethod
    def load(path: Path) -> list[dict[str, Any]]:
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            return []
        if text.startswith("["):
            return json.loads(text)
        return [json.loads(line) for line in text.splitlines() if line.strip()]

    def run(self, rows: list[dict[str, Any]], on_trigger: Callable[[dict[str, Any]], None] | None = None) -> SimulationResult:
        result = SimulationResult()
        for raw in rows:
            sid = str(raw["symbol"])
            if sid not in self.breakout_levels:
                continue
            snap = build_snapshot(sid, raw)
            sm = self.states.setdefault(sid, IntradayStateMachine())
            triggered, reason = sm.evaluate(snap, self.breakout_levels[sid], 4.0, self.buffer_pct)
            result.processed += 1
            result.add_reason(reason)
            row = {
                "symbol": sid,
                "observed_at": snap.observed_at,
                "snapshot_id": snap.snapshot_id,
                "state": sm.state.value,
                "reason": reason,
                "triggered": triggered,
            }
            result.states.append(row)
            if triggered:
                result.triggers += 1
                if on_trigger:
                    on_trigger(row)
        return result
