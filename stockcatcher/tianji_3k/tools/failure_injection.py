from __future__ import annotations

import argparse
from pathlib import Path

from ..core.failure_injection import FailureInjector, write_report


def main() -> int:
    parser = argparse.ArgumentParser(description="Run deterministic Tianji 3K full-day failure injection test")
    parser.add_argument("--root", type=Path, default=Path("tianji_3k") / "test_artifacts" / "failure_injection")
    parser.add_argument("--report", type=Path, default=None)
    args = parser.parse_args()
    result = FailureInjector(args.root).run()
    report = args.report or args.root / "failure_injection_report.json"
    write_report(result, report)
    print(f"FAILURE_INJECTION {'PASS' if result.passed else 'FAIL'}")
    print(f"steps={result.processed_steps} predictions={result.predictions_created} recoveries={result.recovery_count} validations={result.validation_count}")
    print(f"report={report}")
    if result.errors:
        for e in result.errors:
            print(f"ERROR {e}")
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
