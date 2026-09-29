from __future__ import annotations

from pathlib import Path
from typing import Iterable

from .calibration_engine import DEFAULT_SCORE_BANDS, PredictionCalibrationEngine


def build_calibration_report(
    predictions: Iterable[dict],
    ground_truth: Iterable[dict],
    bands=DEFAULT_SCORE_BANDS,
) -> dict:
    engine = PredictionCalibrationEngine(score_bands=tuple(bands))
    return engine.build_report(list(predictions), list(ground_truth))


def build_from_ledger(prediction_root: str | Path, trade_date: str | None = None) -> dict:
    return PredictionCalibrationEngine().build_from_ledger(prediction_root, trade_date)


def write_calibration_report(root: str | Path, report: dict, name: str = "score_calibration.json") -> Path:
    return PredictionCalibrationEngine.write_report(Path(root) / name, report)
