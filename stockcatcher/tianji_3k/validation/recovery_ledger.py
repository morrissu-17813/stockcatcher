from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class RecoveryLedger:
    """Append-only operational journal used to reconstruct interrupted work."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def append(self, trade_date: str, event: dict[str, Any]) -> None:
        p = self.root / f"{trade_date}.jsonl"
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")

    def events(self, trade_date: str) -> list[dict[str, Any]]:
        p = self.root / f"{trade_date}.jsonl"
        if not p.exists():
            return []
        out = []
        for line in p.read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
        return out
