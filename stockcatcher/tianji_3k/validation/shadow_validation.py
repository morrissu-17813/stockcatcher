from __future__ import annotations

"""Offline, read-only shadow validation for historical Tianji 3K records.

This module never imports the live runner, calls market-data APIs, sends Telegram
messages, or edits source records. Outputs are written only to the caller-supplied
output directory.
"""

import argparse
import csv
import json
import statistics
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

SCHEMA_VERSION = "shadow-validation-v1"
PREDICTION_EVENT = "INTRADAY_3K_PREDICTION"
SAMPLE_EVENT = "POST_SIGNAL_PRICE_SAMPLE"
FINAL_EVENT = "POST_SIGNAL_TRACKING_FINAL"


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except (OSError, ValueError, TypeError):
        return None


def _read_jsonl(path: Path) -> tuple[list[dict[str, Any]], int]:
    rows: list[dict[str, Any]] = []
    malformed = 0
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return rows, malformed
    for line in lines:
        if not line.strip():
            continue
        try:
            value = json.loads(line)
            if isinstance(value, dict):
                rows.append(value)
            else:
                malformed += 1
        except ValueError:
            malformed += 1
    return rows, malformed


def _first(*values: Any) -> Any:
    return next((v for v in values if v not in (None, "")), None)


def _float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        result = float(value)
        return result if result == result and abs(result) != float("inf") else None
    except (TypeError, ValueError):
        return None


def _pct(entry: Any, price: Any) -> float | None:
    e, p = _float(entry), _float(price)
    if e is None or p is None or e <= 0 or p <= 0:
        return None
    return round((p / e - 1) * 100, 4)


def _event_files(prediction_root: Path) -> Iterable[Path]:
    if prediction_root.exists():
        yield from sorted(prediction_root.glob("*/*/events.jsonl"))


def _read_excel_signals(xlsx_path: Path | None) -> tuple[list[dict[str, Any]], str | None]:
    if not xlsx_path:
        return [], None
    if not xlsx_path.exists():
        return [], f"Excel file not found: {xlsx_path}"
    try:
        from openpyxl import load_workbook
    except ImportError:
        return [], "openpyxl is required only when importing an .xlsx historical signal file"
    try:
        wb = load_workbook(xlsx_path, read_only=True, data_only=True)
        ws = wb["22筆訊號品質比較"] if "22筆訊號品質比較" in wb.sheetnames else wb[wb.sheetnames[0]]
        iterator = ws.iter_rows(values_only=True)
        headers = [str(v).strip() if v is not None else "" for v in next(iterator, ())]
        rows = []
        for values in iterator:
            raw = dict(zip(headers, values))
            symbol = _first(raw.get("股票代碼"), raw.get("symbol"))
            if symbol is None:
                continue
            symbol = str(symbol).strip().split(".")[0]
            signal_time = _first(raw.get("訊號時間"), raw.get("signal_time"))
            signal_level = _first(raw.get("訊號級別"), raw.get("signal_level"))
            signal_price = _first(raw.get("訊號價"), raw.get("signal_price"))
            quote_price = _first(raw.get("最後有效價"), raw.get("last_valid_price"))
            proxy_return = _float(_first(raw.get("訊號後代理報酬(%)"), raw.get("proxy_return_pct")))
            rows.append({
                "record_source": "historical_xlsx",
                "trade_date": "2026-10-14" if "2026-10-14" in xlsx_path.name else None,
                "symbol": symbol,
                "name": _first(raw.get("股票名稱"), raw.get("name")),
                "signal_time": str(signal_time) if signal_time is not None else None,
                "signal_level": str(signal_level) if signal_level is not None else None,
                "signal_price": _float(signal_price),
                "breakout_base": _float(raw.get("突破基準")),
                "extension_pct": _float(raw.get("高於突破基準(%)")),
                "projected_volume_ratio": _float(_first(raw.get("預估量比(x)"), raw.get("projected_volume_ratio"))),
                "last_quote_time": str(raw.get("最後有效報價時間")) if raw.get("最後有效報價時間") is not None else None,
                "last_quote_price": _float(quote_price),
                "proxy_return_pct": proxy_return if proxy_return is not None else _pct(signal_price, quote_price),
                "proxy_quality": _first(raw.get("品質分類"), raw.get("proxy_quality")),
                "confidence": _first(raw.get("判定信心"), raw.get("confidence")),
                "evidence": _first(raw.get("判定理由／證據"), raw.get("evidence")),
                "prediction_id": None,
                "ledger_match": "UNMATCHED_NOT_IN_LEDGER",
                "t_plus_5m_status": "UNKNOWN",
                "t_plus_5m_return_pct": None,
                "t_plus_15m_status": "UNKNOWN",
                "t_plus_15m_return_pct": None,
                "t_plus_30m_status": "UNKNOWN",
                "t_plus_30m_return_pct": None,
                "close_return_pct": None,
                "ground_truth_available": None,
                "mfe_pct": None,
                "mae_pct": None,
                "duplicate_signal_key": None,
            })
        wb.close()
        return rows, None
    except Exception as exc:  # defensive import boundary for user-supplied historical files
        return [], f"Could not read Excel file: {type(exc).__name__}: {exc}"


def collect_predictions(prediction_root: Path, validation_root: Path) -> tuple[dict[str, dict[str, Any]], Counter, list[str]]:
    predictions: dict[str, dict[str, Any]] = {}
    event_counts: Counter = Counter()
    warnings: list[str] = []
    malformed_total = 0
    for path in _event_files(prediction_root):
        events, malformed = _read_jsonl(path)
        malformed_total += malformed
        for event in events:
            event_type = str(event.get("event_type") or "UNKNOWN")
            event_counts[event_type] += 1
            if event_type == PREDICTION_EVENT:
                pid = str(event.get("prediction_id") or "").strip()
                if pid:
                    predictions.setdefault(pid, dict(event))
    master = validation_root / "master_prediction_log.jsonl"
    events, malformed = _read_jsonl(master)
    malformed_total += malformed
    for event in events:
        event_counts[str(event.get("event_type") or "UNKNOWN")] += 1
        if event.get("event_type") != PREDICTION_EVENT:
            continue
        pid = str(event.get("prediction_id") or "").strip()
        if pid:
            predictions.setdefault(pid, dict(event))
    # Merge all per-symbol events after prediction identities are known.
    for path in _event_files(prediction_root):
        events, _ = _read_jsonl(path)
        for event in events:
            if event.get("event_type") not in {SAMPLE_EVENT, FINAL_EVENT}:
                continue
            pid = str(event.get("prediction_id") or "").strip()
            if pid and pid in predictions:
                predictions[pid].setdefault("_shadow_events", []).append(dict(event))
    if malformed_total:
        warnings.append(f"Malformed JSONL lines skipped: {malformed_total}")
    if not master.exists():
        warnings.append("Master prediction ledger not found; per-symbol event files only were scanned")
    return predictions, event_counts, warnings


def normalize_prediction(prediction: dict[str, Any]) -> dict[str, Any]:
    context = prediction.get("context") or {}
    trigger = prediction.get("trigger_snapshot") or {}
    volume = prediction.get("volume_snapshot") or {}
    row: dict[str, Any] = {
        "record_source": "prediction_ledger",
        "trade_date": _first(prediction.get("trade_date"), context.get("trade_date")),
        "symbol": str(_first(prediction.get("symbol"), context.get("symbol"), "")),
        "name": _first(trigger.get("name"), context.get("name")),
        "signal_time": _first(prediction.get("created_at"), trigger.get("observed_at")),
        "signal_level": _first(trigger.get("signal_level"), volume.get("signal_level")),
        "signal_price": _float(_first(trigger.get("current_price"), trigger.get("close"))),
        "breakout_base": _float(_first(trigger.get("breakout_level"), context.get("breakout_level"))),
        "extension_pct": None,
        "projected_volume_ratio": _float(volume.get("projected_ratio")),
        "last_quote_time": None,
        "last_quote_price": None,
        "proxy_return_pct": None,
        "proxy_quality": None,
        "confidence": _first(trigger.get("prediction_score"), context.get("prediction_score")),
        "evidence": None,
        "prediction_id": prediction.get("prediction_id"),
        "ledger_match": "LEDGER_RECORD",
        "t_plus_5m_status": "UNKNOWN",
        "t_plus_5m_return_pct": None,
        "t_plus_15m_status": "UNKNOWN",
        "t_plus_15m_return_pct": None,
        "t_plus_30m_status": "UNKNOWN",
        "t_plus_30m_return_pct": None,
        "close_return_pct": None,
        "ground_truth_available": None,
        "mfe_pct": None,
        "mae_pct": None,
        "duplicate_signal_key": None,
    }
    for event in prediction.get("_shadow_events", []):
        event_type = event.get("event_type")
        if event_type == SAMPLE_EVENT:
            key = str(event.get("sample_type") or "")
            status = str(event.get("status") or "OBSERVED")
            suffix = {"T_PLUS_5M": "5m", "T_PLUS_15M": "15m", "T_PLUS_30M": "30m"}.get(key)
            if suffix:
                row[f"t_plus_{suffix}_status"] = status
                row[f"t_plus_{suffix}_return_pct"] = _float(event.get("return_pct"))
        elif event_type == FINAL_EVENT:
            row["close_return_pct"] = _float(event.get("close_return_pct"))
            row["ground_truth_available"] = bool(event.get("ground_truth_available"))
            row["mfe_pct"] = _float(event.get("mfe_pct"))
            row["mae_pct"] = _float(event.get("mae_pct"))
    return row


def _duplicate_keys(rows: list[dict[str, Any]]) -> None:
    counts = Counter()
    for row in rows:
        key = "|".join(str(row.get(k) or "") for k in ("trade_date", "symbol", "signal_time", "signal_level"))
        counts[key] += 1
        row["duplicate_signal_key"] = key
    for row in rows:
        if counts[row["duplicate_signal_key"]] > 1:
            row["duplicate_signal_key"] += "|DUPLICATE"


def _summary(rows: list[dict[str, Any]], event_counts: Counter, warnings: list[str]) -> dict[str, Any]:
    ledger_rows = [r for r in rows if r.get("record_source") == "prediction_ledger"]
    milestones: dict[str, Any] = {}
    for label in ("5m", "15m", "30m"):
        returns = [r[f"t_plus_{label}_return_pct"] for r in ledger_rows if r.get(f"t_plus_{label}_return_pct") is not None]
        known = [r for r in ledger_rows if r.get(f"t_plus_{label}_status") not in (None, "UNKNOWN", "MISSED_WINDOW")]
        milestones[label] = {
            "known_count": len(known),
            "positive_count": sum(1 for x in returns if x > 0),
            "negative_count": sum(1 for x in returns if x < 0),
            "flat_count": sum(1 for x in returns if x == 0),
            "mean_return_pct": round(statistics.mean(returns), 4) if returns else None,
            "status_unknown_or_missing_count": sum(1 for r in ledger_rows if r.get(f"t_plus_{label}_status") in (None, "UNKNOWN", "MISSED_WINDOW")),
        }
    proxy = [r["proxy_return_pct"] for r in rows if r.get("record_source") == "historical_xlsx" and r.get("proxy_return_pct") is not None]
    return {
        "schema_version": SCHEMA_VERSION,
        "mode": "READ_ONLY_SHADOW",
        "formal_strategy_modified": False,
        "api_calls_made": 0,
        "telegram_messages_sent": 0,
        "records_total": len(rows),
        "prediction_ledger_records": len(ledger_rows),
        "historical_xlsx_records": sum(1 for r in rows if r.get("record_source") == "historical_xlsx"),
        "ledger_event_counts": dict(event_counts),
        "milestones": milestones,
        "historical_xlsx_proxy": {
            "valid_count": len(proxy),
            "positive_count": sum(1 for x in proxy if x > 0),
            "negative_count": sum(1 for x in proxy if x < 0),
            "flat_count": sum(1 for x in proxy if x == 0),
            "mean_proxy_return_pct": round(statistics.mean(proxy), 4) if proxy else None,
            "warning": "Proxy return is not verified execution P&L and is not interchangeable with T+5/T+15/T+30 milestone returns.",
        },
        "warnings": warnings,
    }


def run_shadow_validation(prediction_root: Path, validation_root: Path, output_dir: Path,
                          signal_xlsx: Path | None = None) -> dict[str, Any]:
    """Read historical records and write normalized CSV/JSON summary only."""
    predictions, event_counts, warnings = collect_predictions(Path(prediction_root), Path(validation_root))
    rows = [normalize_prediction(p) for p in predictions.values()]
    xlsx_rows, xlsx_warning = _read_excel_signals(Path(signal_xlsx) if signal_xlsx else None)
    if xlsx_warning:
        warnings.append(xlsx_warning)
    # Match only on date + symbol + minute-level signal time + level. No fuzzy joins.
    ledger_index: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for row in rows:
        ts = str(row.get("signal_time") or "")[:16]
        ledger_index[(str(row.get("trade_date") or ""), str(row.get("symbol") or ""), ts, str(row.get("signal_level") or ""))] = row
    for xrow in xlsx_rows:
        key = (str(xrow.get("trade_date") or ""), str(xrow.get("symbol") or ""), str(xrow.get("signal_time") or "")[:16], str(xrow.get("signal_level") or ""))
        match = ledger_index.get(key)
        if match:
            xrow["prediction_id"] = match.get("prediction_id")
            xrow["ledger_match"] = "EXACT_KEY_MATCH"
            for field in ("t_plus_5m_status", "t_plus_5m_return_pct", "t_plus_15m_status", "t_plus_15m_return_pct", "t_plus_30m_status", "t_plus_30m_return_pct", "close_return_pct", "ground_truth_available", "mfe_pct", "mae_pct"):
                xrow[field] = match.get(field)
    all_rows = rows + xlsx_rows
    _duplicate_keys(all_rows)
    summary = _summary(all_rows, event_counts, warnings)
    output_dir = Path(output_dir)
    # Never overwrite an earlier validation run: each run is an immutable snapshot.
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(
            f"Output directory is not empty; choose a new directory to preserve prior reports: {output_dir}"
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    fields = list(dict.fromkeys(k for row in all_rows for k in row.keys()))
    csv_path = output_dir / "shadow_validation_dataset.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(all_rows)
    json_path = output_dir / "shadow_validation_dataset.json"
    json_path.write_text(json.dumps(all_rows, ensure_ascii=False, indent=2), encoding="utf-8")
    summary_path = output_dir / "shadow_validation_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    summary["output_files"] = {"csv": str(csv_path), "dataset_json": str(json_path), "summary_json": str(summary_path)}
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline read-only Tianji 3K shadow validation")
    parser.add_argument("--prediction-root", type=Path, required=True, help="Existing predictions/ directory")
    parser.add_argument("--validation-root", type=Path, required=True, help="Existing validation/ directory")
    parser.add_argument("--output-dir", type=Path, required=True, help="New output directory; source records are never modified")
    parser.add_argument("--signal-xlsx", type=Path, help="Optional historical signal workbook, e.g. 10/14 quality comparison")
    args = parser.parse_args()
    summary = run_shadow_validation(args.prediction_root, args.validation_root, args.output_dir, args.signal_xlsx)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
