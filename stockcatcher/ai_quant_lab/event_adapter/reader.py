"""Read-only JSONL event reader for the isolated Lab inbox."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Iterator, Any

ALLOWED_EVENT_TYPES = {
    "signal.created", "prediction.recorded", "prediction.validated",
    "telegram.sent", "telegram.suppressed", "session.closed",
}

def read_events(path: str | Path) -> Iterator[dict[str, Any]]:
    """Yield valid Lab events; malformed lines are skipped, source file is never changed."""
    source = Path(path)
    if not source.exists():
        return
    with source.open("r", encoding="utf-8") as stream:
        for line_no, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            if event.get("event_type") not in ALLOWED_EVENT_TYPES:
                continue
            if not event.get("event_id") or not event.get("occurred_at"):
                continue
            event["_source_line"] = line_no
            yield event
