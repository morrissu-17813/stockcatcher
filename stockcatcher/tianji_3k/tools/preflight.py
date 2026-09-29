from __future__ import annotations

import importlib
import os
from pathlib import Path


def run(repo_root: Path) -> int:
    root = Path(repo_root).resolve()
    pkg = root / "tianji_3k"
    checks = [
        ("package", (pkg / "__init__.py").exists()),
        ("runner", (pkg / "runner.py").exists()),
        ("shared_env", (root.parent / ".env").exists() or (root / ".env").exists()),
        ("stage0", (pkg / "tools" / "stage0_production.py").exists()),
        ("stage1", (pkg / "stage1" / "trend_engine.py").exists()),
        ("stage2", (pkg / "stage2" / "breakout_engine.py").exists()),
        ("stage3", (pkg / "stage3" / "volume_engine.py").exists()),
        ("ledger", (pkg / "validation" / "prediction_ledger.py").exists()),
    ]
    import_targets = [
        "tianji_3k.runner",
        "tianji_3k.core.state_machine",
        "tianji_3k.core.volume_predictor",
        "tianji_3k.validation.prediction_ledger",
        "tianji_3k.notification.telegram",
    ]
    for target in import_targets:
        try:
            importlib.import_module(target)
            checks.append((f"import:{target}", True))
        except Exception:
            checks.append((f"import:{target}", False))

    ok = True
    print("=" * 64)
    print("天機 3K PREFLIGHT")
    print("=" * 64)
    for name, passed in checks:
        print(f"{'PASS' if passed else 'FAIL':<5} {name}")
        ok &= passed

    # Never print secret values. Only expose presence/absence.
    print(f"ENV_FUGLE_API_KEY={'SET' if os.getenv('FUGLE_API_KEY') else 'NOT_SET'}")
    print(f"ENV_TELEGRAM_BOT_TOKEN={'SET' if os.getenv('TELEGRAM_BOT_TOKEN') else 'NOT_SET'}")
    print(f"ENV_TELEGRAM_CHAT_ID={'SET' if os.getenv('TELEGRAM_CHAT_ID') else 'NOT_SET'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(run(Path(__file__).resolve().parents[2]))


def run_preflight(repo_root: Path | None = None) -> dict:
    root = Path(repo_root or Path(__file__).resolve().parents[2]).resolve()
    pkg = root / "tianji_3k"
    checks = {}
    checks["package"] = (pkg / "__init__.py").exists()
    checks["runner"] = (pkg / "runner.py").exists()
    checks["shared_env"] = (root / ".env").exists() or (root.parent / ".env").exists()
    for name, rel in {
        "stage0": "tools/stage0_production.py",
        "stage1": "stage1/trend_engine.py",
        "stage2": "stage2/breakout_engine.py",
        "stage3": "stage3/volume_engine.py",
        "ledger": "validation/prediction_ledger.py",
        "recovery": "core/recovery.py",
        "simulator": "core/simulator.py",
        "prediction_score": "core/prediction_score.py",
        "volume_predictor": "core/volume_predictor.py",
        "finmind_budget": "data/finmind_budget.py",
        "daily_refresh": "data/daily_refresh.py",
        "calibration_engine": "validation/calibration_engine.py",
    }.items():
        checks[name] = (pkg / rel).exists()
    for target in (
        "tianji_3k.runner",
        "tianji_3k.data.mis",
        "tianji_3k.data.finmind_budget",
        "tianji_3k.core.prediction_score",
        "tianji_3k.core.volume_predictor",
        "tianji_3k.validation.prediction_ledger",
        "tianji_3k.validation.calibration_engine",
        "tianji_3k.notification.telegram",
    ):
        try:
            importlib.import_module(target)
            checks[f"import:{target}"] = True
        except Exception:
            checks[f"import:{target}"] = False
    return {
        "ok": all(checks.values()),
        "checks": checks,
        "env_presence": {
            "FUGLE_API_KEY": bool(os.getenv("FUGLE_API_KEY")),
            "TELEGRAM_BOT_TOKEN": bool(os.getenv("TELEGRAM_BOT_TOKEN")),
            "TELEGRAM_CHAT_ID": bool(os.getenv("TELEGRAM_CHAT_ID")),
        },
    }
