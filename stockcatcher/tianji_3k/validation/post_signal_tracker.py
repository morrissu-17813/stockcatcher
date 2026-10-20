from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

TAIPEI = timezone(timedelta(hours=8))
MILESTONES_MINUTES = (5, 15, 30)
MILESTONE_GRACE_SECONDS = 120


def _dt(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=TAIPEI)
    except (TypeError, ValueError):
        return None


def _price(snapshot: Any) -> float:
    value = snapshot.get("current_price") if isinstance(snapshot, dict) else getattr(snapshot, "current_price", None)
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _observed_at(snapshot: Any):
    return snapshot.get("observed_at") if isinstance(snapshot, dict) else getattr(snapshot, "observed_at", None)


def _snapshot_id(snapshot: Any):
    if isinstance(snapshot, dict):
        return snapshot.get("snapshot_id") or snapshot.get("data_identity")
    return getattr(snapshot, "snapshot_id", None) or getattr(snapshot, "data_identity", None)


class PostSignalTracker:
    """Persist post-signal price milestones without making extra market-data calls.

    It consumes MIS snapshots already fetched by Radar. State is atomically saved
    per trading day so process restarts retain extrema, last snapshot identity,
    and milestone completion.
    """

    def __init__(self, prediction_root: Path, ledger):
        self.prediction_root = Path(prediction_root)
        self.ledger = ledger
        self._day_state: dict[str, dict[str, Any]] = {}

    def _state_path(self, trade_date: str) -> Path:
        return self.prediction_root / trade_date / "post_signal_tracking.json"

    def _load_day(self, trade_date: str) -> dict[str, Any]:
        if trade_date in self._day_state:
            return self._day_state[trade_date]
        path = self._state_path(trade_date)
        try:
            state = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
            if not isinstance(state, dict):
                state = {}
        except (OSError, ValueError, TypeError):
            state = {}
        self._day_state[trade_date] = state
        return state

    def _save_day(self, trade_date: str, state: dict[str, Any]) -> None:
        path = self._state_path(trade_date)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(path)

    def observe(self, trade_date: str, snapshots: dict[str, Any]) -> int:
        """Update each prediction from current valid MIS snapshots; return changed count."""
        state = self._load_day(trade_date)
        changed = 0
        predictions = [p for p in self.ledger.iter_predictions(trade_date)
                       if p.get("event_type") == "INTRADAY_3K_PREDICTION"]
        for prediction in predictions:
            prediction_id = str(prediction.get("prediction_id") or "")
            symbol = str(prediction.get("symbol") or "")
            if not prediction_id or not symbol or symbol not in snapshots:
                continue
            snapshot = snapshots[symbol]
            price = _price(snapshot)
            observed = _dt(_observed_at(snapshot))
            entry = prediction.get("trigger_snapshot", {}) or {}
            entry_price = _price(entry)
            entry_at = _dt(prediction.get("created_at") or entry.get("observed_at"))
            if price <= 0 or entry_price <= 0 or observed is None or entry_at is None or observed < entry_at:
                continue
            snap_id = str(_snapshot_id(snapshot) or "")
            item = state.get(prediction_id)
            if isinstance(item, dict) and str(item.get("status", "")).startswith("FINALIZED"):
                continue
            # The append-only ledger is authoritative if a crash happened after
            # appending a sample but before the atomic tracking-state save.
            existing_samples = {
                str(e.get("sample_type")): e
                for e in self.ledger.events_for_symbol(trade_date, symbol)
                if e.get("event_type") == "POST_SIGNAL_PRICE_SAMPLE"
                and e.get("prediction_id") == prediction_id
            }
            if not isinstance(item, dict):
                item = {
                    "prediction_id": prediction_id,
                    "trade_date": trade_date,
                    "symbol": symbol,
                    "entry_at": entry_at.isoformat(),
                    "entry_price": entry_price,
                    "last_snapshot_id": "",
                    "max_price": entry_price,
                    "min_price": entry_price,
                    "milestones": {},
                    "status": "TRACKING",
                }
                state[prediction_id] = item
                changed += 1
            if snap_id and snap_id == item.get("last_snapshot_id"):
                continue
            item["last_snapshot_id"] = snap_id
            item["last_observed_at"] = observed.isoformat()
            item["last_price"] = price
            item["max_price"] = max(float(item.get("max_price", entry_price)), price)
            item["min_price"] = min(float(item.get("min_price", entry_price)), price)
            elapsed = max(0.0, (observed - entry_at).total_seconds())
            item["elapsed_seconds"] = round(elapsed, 3)
            item["mfe_pct"] = round((float(item["max_price"]) / entry_price - 1) * 100, 4)
            item["mae_pct"] = round((float(item["min_price"]) / entry_price - 1) * 100, 4)
            for minutes in MILESTONES_MINUTES:
                key = f"T_PLUS_{minutes}M"
                target_seconds = minutes * 60
                if key not in item["milestones"] and key in existing_samples:
                    item["milestones"][key] = {
                        k: v for k, v in existing_samples[key].items() if k != "event_type"
                    }
                if elapsed < target_seconds or key in item["milestones"]:
                    continue
                if elapsed > target_seconds + MILESTONE_GRACE_SECONDS:
                    # Never label a much-later quote as an exact +5/+15/+30m sample.
                    missed = {
                        "event_type": "POST_SIGNAL_PRICE_SAMPLE",
                        "sample_type": key,
                        "prediction_id": prediction_id,
                        "trade_date": trade_date,
                        "symbol": symbol,
                        "status": "MISSED_WINDOW",
                        "target_elapsed_seconds": target_seconds,
                        "observed_elapsed_seconds": round(elapsed, 3),
                        "reason": "NO_VALID_MIS_SNAPSHOT_WITHIN_GRACE_WINDOW",
                        "recorded_at": datetime.now(TAIPEI).isoformat(),
                    }
                    self.ledger.append_event(trade_date, symbol, missed)
                    item["milestones"][key] = {k: v for k, v in missed.items() if k != "event_type"}
                    continue
                sample = {
                    "event_type": "POST_SIGNAL_PRICE_SAMPLE",
                    "sample_type": key,
                    "prediction_id": prediction_id,
                    "trade_date": trade_date,
                    "symbol": symbol,
                    "prediction_created_at": prediction.get("created_at"),
                    "entry_price": entry_price,
                    "sample_price": price,
                    "sample_at": observed.isoformat(),
                    "elapsed_seconds": round(elapsed, 3),
                    "return_pct": round((price / entry_price - 1) * 100, 4),
                    "max_price_since_signal": item["max_price"],
                    "min_price_since_signal": item["min_price"],
                    "mfe_pct": item["mfe_pct"],
                    "mae_pct": item["mae_pct"],
                    "snapshot_id": snap_id,
                    "source": "MIS_RADAR_SNAPSHOT",
                }
                self.ledger.append_event(trade_date, symbol, sample)
                item["milestones"][key] = {k: v for k, v in sample.items() if k != "event_type"}
            changed += 1
        if changed:
            self._save_day(trade_date, state)
        return changed

    def finalize_close(self, trade_date: str, ground_truth_by_symbol: dict[str, dict]) -> int:
        """Write one idempotent per-prediction close/MFE/MAE summary."""
        state = self._load_day(trade_date)
        written = 0
        predictions = [p for p in self.ledger.iter_predictions(trade_date)
                       if p.get("event_type") == "INTRADAY_3K_PREDICTION"]
        for prediction in predictions:
            prediction_id = str(prediction.get("prediction_id") or "")
            symbol = str(prediction.get("symbol") or "")
            if not prediction_id or not symbol:
                continue
            events = self.ledger.events_for_symbol(trade_date, symbol)
            if any(e.get("event_type") == "POST_SIGNAL_TRACKING_FINAL" and e.get("prediction_id") == prediction_id for e in events):
                continue
            gt = ground_truth_by_symbol.get(symbol)
            item = state.get(prediction_id, {})
            entry = prediction.get("trigger_snapshot", {}) or {}
            entry_price = _price(entry)
            close = None
            if isinstance(gt, dict):
                try:
                    close = float(gt.get("close")) if gt.get("close") is not None else None
                except (TypeError, ValueError):
                    close = None
            if close is not None and close > 0 and entry_price > 0:
                item["max_price"] = max(float(item.get("max_price", entry_price)), close)
                item["min_price"] = min(float(item.get("min_price", entry_price)), close)
                item["mfe_pct"] = round((float(item["max_price"]) / entry_price - 1) * 100, 4)
                item["mae_pct"] = round((float(item["min_price"]) / entry_price - 1) * 100, 4)
            missing = [f"T_PLUS_{m}M" for m in MILESTONES_MINUTES if f"T_PLUS_{m}M" not in (item.get("milestones") or {})]
            row = {
                "event_type": "POST_SIGNAL_TRACKING_FINAL",
                "prediction_id": prediction_id,
                "trade_date": trade_date,
                "symbol": symbol,
                "entry_at": prediction.get("created_at"),
                "entry_price": entry_price or None,
                "close_price": close,
                "close_return_pct": round((close / entry_price - 1) * 100, 4) if close and entry_price > 0 else None,
                "max_price_since_signal": item.get("max_price"),
                "min_price_since_signal": item.get("min_price"),
                "mfe_pct": item.get("mfe_pct"),
                "mae_pct": item.get("mae_pct"),
                "milestones": item.get("milestones", {}),
                "missing_milestones": missing,
                "ground_truth_available": bool(isinstance(gt, dict) and close is not None),
                "ground_truth_3k": gt.get("ground_truth_3k") if isinstance(gt, dict) else None,
                "finalized_at": datetime.now(TAIPEI).isoformat(),
                "metric_scope": "OBSERVED_MIS_QUOTES_ONLY",
            }
            self.ledger.append_event(trade_date, symbol, row)
            item["status"] = "FINALIZED" if row["ground_truth_available"] else "FINALIZED_GT_UNAVAILABLE"
            item["finalized_at"] = row["finalized_at"]
            written += 1
        if written:
            self._save_day(trade_date, state)
        return written

    def write_report(self, trade_date: str) -> dict[str, str]:
        """Export one row per prediction for quick post-close manual review."""
        import csv

        predictions = [p for p in self.ledger.iter_predictions(trade_date)
                       if p.get("event_type") == "INTRADAY_3K_PREDICTION"]
        rows = []
        for prediction in predictions:
            pid = str(prediction.get("prediction_id") or "")
            symbol = str(prediction.get("symbol") or "")
            events = self.ledger.events_for_symbol(trade_date, symbol)
            final = next((e for e in reversed(events)
                          if e.get("event_type") == "POST_SIGNAL_TRACKING_FINAL"
                          and e.get("prediction_id") == pid), {})
            samples = {str(e.get("sample_type")): e for e in events
                       if e.get("event_type") == "POST_SIGNAL_PRICE_SAMPLE"
                       and e.get("prediction_id") == pid}
            row = {
                "trade_date": trade_date,
                "prediction_id": pid,
                "symbol": symbol,
                "prediction_created_at": prediction.get("created_at"),
                "entry_price": final.get("entry_price") or _price(prediction.get("trigger_snapshot", {})) or None,
                "t_plus_5m_price": (samples.get("T_PLUS_5M") or {}).get("sample_price"),
                "t_plus_5m_status": (samples.get("T_PLUS_5M") or {}).get("status", "NOT_REACHED_OR_NOT_RECORDED"),
                "t_plus_15m_price": (samples.get("T_PLUS_15M") or {}).get("sample_price"),
                "t_plus_15m_status": (samples.get("T_PLUS_15M") or {}).get("status", "NOT_REACHED_OR_NOT_RECORDED"),
                "t_plus_30m_price": (samples.get("T_PLUS_30M") or {}).get("sample_price"),
                "t_plus_30m_status": (samples.get("T_PLUS_30M") or {}).get("status", "NOT_REACHED_OR_NOT_RECORDED"),
                "close_price": final.get("close_price"),
                "close_return_pct": final.get("close_return_pct"),
                "max_price_since_signal": final.get("max_price_since_signal"),
                "min_price_since_signal": final.get("min_price_since_signal"),
                "mfe_pct": final.get("mfe_pct"),
                "mae_pct": final.get("mae_pct"),
                "ground_truth_available": final.get("ground_truth_available", False),
                "ground_truth_3k": final.get("ground_truth_3k"),
                "missing_milestones": ",".join(final.get("missing_milestones", [])),
            }
            rows.append(row)
        out_root = self.ledger.validation_root
        out_root.mkdir(parents=True, exist_ok=True)
        csv_path = out_root / f"post_signal_tracking_{trade_date}.csv"
        json_path = out_root / f"post_signal_tracking_{trade_date}.json"
        fieldnames = list(rows[0].keys()) if rows else [
            "trade_date", "prediction_id", "symbol", "prediction_created_at", "entry_price",
            "t_plus_5m_price", "t_plus_5m_status", "t_plus_15m_price", "t_plus_15m_status",
            "t_plus_30m_price", "t_plus_30m_status", "close_price", "close_return_pct",
            "max_price_since_signal", "min_price_since_signal", "mfe_pct", "mae_pct",
            "ground_truth_available", "ground_truth_3k", "missing_milestones",
        ]
        with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        tmp = json_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(json_path)
        return {"csv": str(csv_path), "json": str(json_path), "rows": str(len(rows))}
