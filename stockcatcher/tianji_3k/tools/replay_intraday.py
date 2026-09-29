from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..core.snapshot import build_snapshot
from ..core.state_machine import IntradayStateMachine


def main(argv=None):
    ap = argparse.ArgumentParser(description="Replay deterministic MIS snapshots through the 3K state machine")
    ap.add_argument("snapshots", type=Path)
    ap.add_argument("--breakout-level", type=float, required=True)
    ap.add_argument("--buffer", type=float, default=0.3)
    args = ap.parse_args(argv)
    rows = json.loads(args.snapshots.read_text(encoding="utf-8"))
    sm = IntradayStateMachine()
    for raw in rows:
        sid = str(raw["symbol"])
        snap = build_snapshot(sid, raw)
        triggered, reason = sm.evaluate(snap, args.breakout_level, 4.0, args.buffer)
        print(json.dumps({"symbol": sid, "observed_at": snap.observed_at, "state": sm.state.value, "reason": reason, "triggered": triggered}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
