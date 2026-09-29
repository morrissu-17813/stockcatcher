from __future__ import annotations

import json
import math
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Iterable, Sequence


DEFAULT_SCORE_BANDS: tuple[tuple[int, int], ...] = (
    (0, 59), (60, 69), (70, 79), (80, 89), (90, 100),
)
DEFAULT_TIME_BANDS: tuple[tuple[int, int], ...] = (
    (9, 9), (10, 10), (11, 11), (12, 12), (13, 13),
)


@dataclass(frozen=True)
class BandStats:
    label: str
    lower: float
    upper: float
    sample_count: int
    hit_count: int
    miss_count: int
    empirical_hit_rate: float | None
    wilson_low: float | None
    wilson_high: float | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class PredictionCalibrationEngine:
    """Historical calibration/audit engine for Tianji 3K predictions.

    This engine is deliberately descriptive. It measures historical outcomes
    against immutable predictions; it does not claim that a raw Score is a
    probability and does not rank stocks or predict future returns.
    """

    def __init__(
        self,
        score_bands: Sequence[tuple[int, int]] = DEFAULT_SCORE_BANDS,
        time_bands: Sequence[tuple[int, int]] = DEFAULT_TIME_BANDS,
        min_samples_for_stable_band: int = 30,
    ) -> None:
        self.score_bands = tuple(score_bands)
        self.time_bands = tuple(time_bands)
        self.min_samples_for_stable_band = int(min_samples_for_stable_band)

    @staticmethod
    def _wilson(hits: int, n: int, z: float = 1.959963984540054) -> tuple[float | None, float | None]:
        if n <= 0:
            return None, None
        p = hits / n
        denom = 1 + z * z / n
        centre = (p + z * z / (2 * n)) / denom
        margin = z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n) / denom
        return max(0.0, centre - margin), min(1.0, centre + margin)

    @staticmethod
    def _score(prediction: dict[str, Any]) -> int | None:
        raw = prediction.get("trigger_snapshot", {}).get("prediction_score")
        if raw is None:
            raw = prediction.get("prediction_score")
        try:
            score = int(raw)
        except (TypeError, ValueError):
            return None
        return score if 0 <= score <= 100 else None

    @staticmethod
    def _hour(prediction: dict[str, Any]) -> int | None:
        raw = prediction.get("created_at") or prediction.get("trigger_snapshot", {}).get("observed_at")
        if not raw:
            return None
        try:
            return int(str(raw)[11:13])
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _key(row: dict[str, Any]) -> tuple[str, str]:
        return str(row.get("trade_date", "")), str(row.get("symbol", ""))

    @staticmethod
    def _prediction_key(prediction: dict[str, Any]) -> str:
        return str(prediction.get("prediction_id") or "")

    @staticmethod
    def _band_stats(values: Iterable[tuple[float, bool]], bands: Sequence[tuple[int, int]]) -> list[dict[str, Any]]:
        rows = list(values)
        result: list[dict[str, Any]] = []
        for lower, upper in bands:
            selected = [hit for value, hit in rows if lower <= value <= upper]
            n = len(selected)
            hits = sum(selected)
            low, high = PredictionCalibrationEngine._wilson(hits, n)
            result.append(BandStats(
                label=f"{lower}-{upper}",
                lower=lower,
                upper=upper,
                sample_count=n,
                hit_count=hits,
                miss_count=n - hits,
                empirical_hit_rate=hits / n if n else None,
                wilson_low=low,
                wilson_high=high,
            ).to_dict())
        return result

    def reconcile(
        self,
        predictions: Iterable[dict[str, Any]],
        ground_truth: Iterable[dict[str, Any]],
    ) -> dict[str, Any]:
        """Join prediction events to Ground Truth without mutating either source."""
        predictions = list(predictions)
        gt_map = {
            self._key(row): row
            for row in ground_truth
            if row.get("ground_truth_3k") is not None
        }

        matched: list[dict[str, Any]] = []
        unmatched = 0
        invalid_score = 0
        for prediction in predictions:
            score = self._score(prediction)
            gt = gt_map.get(self._key(prediction))
            if score is None:
                invalid_score += 1
                continue
            if gt is None:
                unmatched += 1
                continue
            matched.append({
                "prediction_id": self._prediction_key(prediction),
                "trade_date": prediction.get("trade_date"),
                "symbol": prediction.get("symbol"),
                "score": score,
                "trigger_hour": self._hour(prediction),
                "hit": bool(gt.get("ground_truth_3k")),
                "ground_truth_3k": bool(gt.get("ground_truth_3k")),
            })

        return {
            "matched": matched,
            "matched_count": len(matched),
            "unmatched_ground_truth": unmatched,
            "invalid_score": invalid_score,
        }

    def build_report(
        self,
        predictions: Iterable[dict[str, Any]],
        ground_truth: Iterable[dict[str, Any]],
    ) -> dict[str, Any]:
        predictions = list(predictions)
        ground_truth = list(ground_truth)
        joined = self.reconcile(predictions, ground_truth)
        rows = joined["matched"]
        score_values = [(r["score"], r["hit"]) for r in rows]
        time_values = [(r["trigger_hour"], r["hit"]) for r in rows if r["trigger_hour"] is not None]

        hits = sum(bool(r["hit"]) for r in rows)
        n = len(rows)
        low, high = self._wilson(hits, n)
        score_bands = self._band_stats(score_values, self.score_bands)
        time_bands = self._band_stats(time_values, self.time_bands)

        for band in score_bands + time_bands:
            band["stable_sample"] = band["sample_count"] >= self.min_samples_for_stable_band

        return {
            "schema_version": "prediction-calibration-v2",
            "method": "historical_empirical_hit_rate",
            "probability_claim": False,
            "generated_from": {
                "prediction_count": len(list(predictions)) if not isinstance(predictions, list) else len(predictions),
                "ground_truth_count": len(list(ground_truth)) if not isinstance(ground_truth, list) else len(ground_truth),
            },
            "sample_count": n,
            "matched_count": n,
            "hit_count": hits,
            "miss_count": n - hits,
            "empirical_hit_rate": hits / n if n else None,
            "wilson_95_low": low,
            "wilson_95_high": high,
            "unmatched_ground_truth": joined["unmatched_ground_truth"],
            "invalid_score": joined["invalid_score"],
            "score_bands": score_bands,
            "bands": score_bands,
            "trigger_time_bands": time_bands,
            "confusion_matrix": {
                "predicted_event_count": n,
                "ground_truth_positive": hits,
                "ground_truth_negative": n - hits,
            },
            "notes": [
                "Score 是可解釋的歷史訊號分數，不是機率。",
                "Wilson 區間僅描述歷史樣本的不確定性，不代表未來命中機率。",
                f"樣本數少於 {self.min_samples_for_stable_band} 的分箱標記為 unstable，避免過度解讀。",
                "同一交易日同一股票的多個 prediction event 會共享該日 Ground Truth，屬事件層級統計，不等同獨立樣本。",
            ],
        }

    def build_from_ledger(self, prediction_root: str | Path, trade_date: str | None = None) -> dict[str, Any]:
        root = Path(prediction_root)
        validation = root.parent / "validation"
        pred_path = validation / "master_prediction_log.jsonl"
        gt_path = validation / "master_ground_truth_log.jsonl"

        def read(path: Path) -> list[dict[str, Any]]:
            if not path.exists():
                return []
            rows = []
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if trade_date is None or str(row.get("trade_date")) == str(trade_date):
                    rows.append(row)
            return rows

        predictions = read(pred_path)
        ground_truth = read(gt_path)
        report = self.build_report(predictions, ground_truth)
        report["trade_date_filter"] = trade_date
        return report

    @staticmethod
    def write_report(path: str | Path, report: dict[str, Any]) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
        return path
