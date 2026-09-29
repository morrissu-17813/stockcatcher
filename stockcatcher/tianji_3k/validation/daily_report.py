from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


def build_daily_report(trade_date, pool, events, ground_truth, validation_rows=None):
    validation_rows = validation_rows or []
    predictions = [e for e in events if e.get("event_type") == "INTRADAY_3K_PREDICTION"]
    sent = [e for e in events if e.get("event_type") in {"INTRADAY_3K_PREDICTION_NOTIFICATION", "NOTIFICATION"} and (e.get("notification_status") or e.get("status")) == "SENT"]
    suppressed = [e for e in events if e.get("event_type") in {"INTRADAY_3K_PREDICTION_NOTIFICATION", "NOTIFICATION"} and (e.get("notification_status") or e.get("status")) == "SUPPRESSED"]
    valid = [v for v in validation_rows if v.get("ground_truth_3k") is not None]
    hits = [v for v in valid if v.get("ground_truth_3k") is True]
    fails = [v for v in valid if v.get("ground_truth_3k") is False]
    return {
        "schema_version": "daily-validation-v2.1",
        "trade_date": trade_date,
        "generated_at": datetime.now().astimezone().isoformat(),
        "pool_count": len(pool),
        "pool_symbols": [str(x.get("symbol")) for x in pool],
        "prediction_count": len(predictions),
        "telegram_sent_count": len(sent),
        "suppressed_count": len(suppressed),
        "ground_truth_symbol_count": len(ground_truth),
        "validated_prediction_count": len(valid),
        "ground_truth_hit_count": len(hits),
        "ground_truth_fail_count": len(fails),
        "hit_rate": (len(hits) / len(valid) if valid else None),
        "validation_rows": validation_rows,
        "notes": "命中率分母為已完成 Ground Truth 的有效 INTRADAY_3K_PREDICTION；SUPPRESSED 不計入。每筆 prediction_id 獨立驗證。",
    }


def write_daily_report(root, trade_date, report):
    p = Path(root) / "daily" / f"{trade_date}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)
    return p
