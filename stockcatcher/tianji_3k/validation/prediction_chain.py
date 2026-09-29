from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .prediction_ledger import PredictionLedger


class PredictionChain:
    """Auditable prediction lifecycle helper.

    It never edits the immutable prediction event. Validation is linked by
    prediction_id and a deterministic chain hash, making post-close auditing
    reproducible.
    """

    def __init__(self, ledger: PredictionLedger):
        self.ledger = ledger

    @staticmethod
    def chain_hash(prediction: dict[str, Any], validation: dict[str, Any]) -> str:
        material = {
            "prediction_id": prediction.get("prediction_id"),
            "trigger_snapshot_id": prediction.get("trigger_snapshot", {}).get("snapshot_id"),
            "prediction_created_at": prediction.get("created_at"),
            "ground_truth_trade_date": validation.get("trade_date"),
            "ground_truth_3k": validation.get("ground_truth_3k"),
            "close": validation.get("close"),
        }
        return hashlib.sha256(json.dumps(material, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    def validate_prediction(self, prediction: dict[str, Any], ground_truth: dict[str, Any]) -> dict[str, Any]:
        row = {
            "event_type": "PREDICTION_VALIDATION",
            "prediction_id": prediction["prediction_id"],
            "trade_date": ground_truth["trade_date"],
            "symbol": prediction["symbol"],
            "prediction_created_at": prediction.get("created_at"),
            "prediction_notification_status": prediction.get("notification_status"),
            "ground_truth_available": True,
            "ground_truth_3k": ground_truth.get("ground_truth_3k"),
            "close": ground_truth.get("close"),
            "gain_pct": ground_truth.get("gain_pct"),
            "volume_ratio": ground_truth.get("volume_ratio"),
            "validated_at": ground_truth.get("validated_at"),
        }
        row["chain_hash"] = self.chain_hash(prediction, ground_truth)
        return row
