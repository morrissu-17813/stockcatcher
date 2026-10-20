"""Read-only reconciliation of real Tianji 3K prediction and validation events."""
from __future__ import annotations
from collections import Counter
from pathlib import Path
from typing import Any
import json
from .production_reader import iter_production_events


def build_production_audit(source_root: str | Path, since: str | None = None) -> dict[str, Any]:
    """Pair prediction events with validation by immutable prediction_id; never infer missing outcomes."""
    events = list(iter_production_events(source_root, since=since))
    predictions: dict[str, dict] = {}
    validations: dict[str, dict] = {}
    notifications: dict[str, dict] = {}
    root = Path(source_root).expanduser().resolve()
    predictions_dir = root / "predictions"
    if predictions_dir.is_dir():
        for path in sorted(predictions_dir.glob("*/*/events.jsonl")):
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                try: raw = json.loads(line)
                except json.JSONDecodeError: continue
                if not isinstance(raw, dict) or raw.get("event_type") != "NOTIFICATION": continue
                pid = str(raw.get("prediction_id") or "")
                if not pid: continue
                if since and str(raw.get("sent_at") or raw.get("created_at") or raw.get("occurred_at") or "")[:10] < since: continue
                notifications[pid] = raw
    for event in events:
        payload = event.get("payload") or {}
        pid = str(payload.get("prediction_id") or "")
        if not pid:
            continue
        if event.get("event_type") == "prediction.recorded":
            # Keep first canonical prediction record for a prediction_id.
            predictions.setdefault(pid, event)
        elif event.get("event_type") == "prediction.validated":
            validations[pid] = event

    rows = []
    notification_counts = Counter()
    validation_counts = Counter()
    for pid, event in sorted(predictions.items(), key=lambda item: str(item[1].get("occurred_at") or ""), reverse=True):
        p = event.get("payload") or {}
        context = p.get("context") or {}
        snap = p.get("trigger_snapshot") or {}
        volume = p.get("volume_snapshot") or {}
        validation_event = validations.get(pid)
        v = (validation_event or {}).get("payload") or {}
        notification_gate_status = str((p.get("notification") or {}).get("status") or p.get("notification_status") or "UNKNOWN")
        notification_event = notifications.get(pid) or {}
        notification_status = str(notification_event.get("notification_status") or notification_event.get("status") or "NOT_RECORDED")
        validation_status = str(v.get("validation_status") or ("VALIDATED" if v.get("ground_truth_available") else "GROUND_TRUTH_MISSING")) if validation_event else "NOT_VALIDATED"
        gt_available = bool(v.get("ground_truth_available") or v.get("ground_truth_3k") is not None) if validation_event else False
        notification_counts[notification_status] += 1
        validation_counts[validation_status] += 1
        rows.append({
            "prediction_id": pid,
            "event_id": event.get("event_id"),
            "source_path": p.get("source_path"),
            "symbol": str(p.get("symbol") or snap.get("symbol") or ""),
            "name": str(context.get("name") or snap.get("name") or p.get("symbol") or ""),
            "trade_date": p.get("trade_date") or v.get("trade_date"),
            "created_at": p.get("created_at") or event.get("occurred_at"),
            "current_price": snap.get("current_price"),
            "up_pct": snap.get("up_pct"),
            "prediction_score": snap.get("prediction_score"),
            "projected_ratio": volume.get("projected_ratio"),
            "live_volume_ratio": volume.get("live_volume_ratio", snap.get("mis_live_volume_ratio")),
            "signal_level": volume.get("signal_level", snap.get("signal_level")),
            "dynamic_candidate": bool(context.get("dynamic_candidate")),
            "dynamic_discovery_pass": bool(context.get("dynamic_discovery_pass")),
            "stage0_pass": context.get("stage0_pass"),
            "stage1_pass": context.get("stage1_pass"),
            "stage2_pass": context.get("stage2_pass"),
            "stage3_pass": context.get("stage3_pass"),
            "notification_status": notification_status,
            "notification_gate_status": notification_gate_status,
            "telegram_message_id": notification_event.get("telegram_message_id"),
            "notification_sent_at": notification_event.get("sent_at"),
            "validation_status": validation_status,
            "ground_truth_available": gt_available,
            "ground_truth_3k": v.get("ground_truth_3k") if gt_available else None,
            "validation_at": v.get("validated_at"),
            "validation_source_path": v.get("source_path"),
            "read_only": True,
        })
    total = len(rows)
    gt_count = sum(1 for r in rows if r["ground_truth_available"])
    return {
        "ok": True,
        "source_root": str(Path(source_root).expanduser().resolve()),
        "source_read_only": True,
        "since": since,
        "prediction_count": total,
        "validated_count": sum(1 for r in rows if r["validation_status"] != "NOT_VALIDATED"),
        "ground_truth_available_count": gt_count,
        "ground_truth_missing_count": total - gt_count,
        "ground_truth_3k_pass_count": sum(1 for r in rows if r["ground_truth_3k"] is True),
        "telegram_sent_count": sum(1 for r in rows if r["notification_status"] == "SENT"),
        "notification_status_counts": dict(notification_counts),
        "validation_status_counts": dict(validation_counts),
        "signals": rows[:200],
        "limitations": [
            "未取得 Ground Truth 的訊號不會計入命中率。",
            "本稽核不會把預測事件轉成紙上訂單，也不會寫入正式版資料夾。",
            "日線 Ground Truth 只能驗證 3K 條件；盤中訊號後的 MFE/MAE 與實際成交路徑需要另外取得逐筆或 5 分 K 行情。",
        ],
    }
