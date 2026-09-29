from __future__ import annotations

import argparse
from pathlib import Path

from tianji_3k.validation.calibration_engine import PredictionCalibrationEngine


def main() -> int:
    ap = argparse.ArgumentParser(description="天機 3K Prediction Calibration Engine")
    ap.add_argument("--prediction-root", default="tianji_3k/predictions")
    ap.add_argument("--trade-date", default=None)
    ap.add_argument("--output", default="tianji_3k/validation/score_calibration.json")
    args = ap.parse_args()

    engine = PredictionCalibrationEngine()
    report = engine.build_from_ledger(args.prediction_root, args.trade_date)
    path = engine.write_report(args.output, report)
    print(f"Calibration report written: {Path(path).resolve()}")
    print(f"Matched={report['matched_count']} Hit={report['hit_count']} Miss={report['miss_count']}")
    print(f"Empirical hit rate={report['empirical_hit_rate']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
