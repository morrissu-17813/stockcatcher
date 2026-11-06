from __future__ import annotations

import argparse
import json
from pathlib import Path

from .prediction_ledger import PredictionLedger


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit or rebuild the Tianji 3K Prediction Ledger master index.")
    parser.add_argument("--root", default="predictions", help="Prediction root directory (default: predictions)")
    parser.add_argument("--date", default=None, help="Optional trade date YYYY-MM-DD")
    parser.add_argument("--rebuild-master", action="store_true", help="Rebuild master_prediction_log.jsonl from canonical per-symbol events")
    args = parser.parse_args()

    ledger = PredictionLedger(Path(args.root))
    if args.rebuild_master:
        print(json.dumps(ledger.rebuild_master_prediction_log(), ensure_ascii=False, indent=2))
    report = ledger.audit(args.date)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("integrity_ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
