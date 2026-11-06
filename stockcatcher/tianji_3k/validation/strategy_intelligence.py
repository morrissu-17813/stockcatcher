from __future__ import annotations

"""Offline strategy intelligence reports for Tianji 3K.

Consumes the normalized shadow-validation dataset. It is read-only with respect
to prediction/validation source records and never imports the live runner.
Only verified close_return_pct contributes to outcome statistics. Historical
workbook proxy_return_pct is reported separately and never mixed with verified
close outcomes.
"""

import argparse
import csv
import html
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable


def _number(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def _wilson(successes: int, total: int, z: float = 1.959963984540054) -> tuple[float | None, float | None]:
    if total <= 0:
        return None, None
    p = successes / total
    denom = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denom
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * total)) / total) / denom
    return max(0.0, centre - margin), min(1.0, centre + margin)


def _stats(rows: list[dict[str, Any]], value_key: str, *, source_filter: str | None = None) -> dict[str, Any]:
    eligible = [
        r for r in rows
        if (source_filter is None or r.get("record_source") == source_filter)
        and _number(r.get(value_key)) is not None
    ]
    values = [_number(r[value_key]) for r in eligible]
    wins = sum(v > 0 for v in values)
    losses = sum(v < 0 for v in values)
    flats = sum(v == 0 for v in values)
    low, high = _wilson(wins, len(values))
    return {
        "sample_count": len(values),
        "positive_count": wins,
        "negative_count": losses,
        "flat_count": flats,
        "positive_rate_excluding_flat": wins / (wins + losses) if wins + losses else None,
        "wilson_95_low": low,
        "wilson_95_high": high,
        "mean_pct": round(statistics.mean(values), 4) if values else None,
        "median_pct": round(statistics.median(values), 4) if values else None,
        "min_pct": round(min(values), 4) if values else None,
        "max_pct": round(max(values), 4) if values else None,
    }


def _bucket(value: float | None, bands: list[tuple[float, float, str]]) -> str:
    if value is None:
        return "UNKNOWN"
    for low, high, label in bands:
        if low <= value < high:
            return label
    return "OUT_OF_RANGE"


def _group_report(rows: list[dict[str, Any]], key_fn) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[key_fn(row)].append(row)
    result = []
    for label in sorted(groups):
        group = groups[label]
        item = {"group": label, **_stats(group, "close_return_pct")}
        item["mfe"] = _stats(group, "mfe_pct")
        item["mae"] = _stats(group, "mae_pct")
        result.append(item)
    return result


def build_intelligence_report(dataset: Iterable[dict[str, Any]]) -> dict[str, Any]:
    rows = [dict(row) for row in dataset]
    ledger = [r for r in rows if r.get("record_source") == "prediction_ledger"]
    workbook = [r for r in rows if r.get("record_source") == "historical_xlsx"]
    verified = [r for r in ledger if _number(r.get("close_return_pct")) is not None]
    unknown = len(ledger) - len(verified)

    score_bands = [
        (0, 60, "00-59"), (60, 70, "60-69"), (70, 80, "70-79"),
        (80, 90, "80-89"), (90, 101, "90-100"),
    ]
    volume_bands = [
        (0, 1, "<1.0x"), (1, 1.5, "1.0-1.49x"),
        (1.5, 2.3, "1.5-2.29x"), (2.3, 999999, ">=2.3x"),
    ]

    def score_group(row: dict[str, Any]) -> str:
        raw = _number(row.get("confidence"))
        return _bucket(raw, score_bands)

    def volume_group(row: dict[str, Any]) -> str:
        raw = _number(row.get("projected_volume_ratio"))
        return _bucket(raw, volume_bands)

    def time_group(row: dict[str, Any]) -> str:
        raw = str(row.get("signal_time") or "")
        if len(raw) < 13:
            return "UNKNOWN"
        try:
            hour = int(raw[11:13])
        except ValueError:
            return "UNKNOWN"
        return "09:00-09:59" if hour == 9 else f"{hour:02d}:00-{hour:02d}:59"

    return {
        "schema_version": "tianji-strategy-intelligence-v1",
        "mode": "OFFLINE_READ_ONLY_RESEARCH",
        "formal_strategy_modified": False,
        "live_runner_imported": False,
        "market_data_api_calls": 0,
        "telegram_messages_sent": 0,
        "record_counts": {
            "all_rows": len(rows),
            "prediction_ledger_events": len(ledger),
            "verified_close_outcomes": len(verified),
            "ledger_outcomes_unknown": unknown,
            "historical_workbook_rows": len(workbook),
        },
        "verified_close_performance": _stats(ledger, "close_return_pct", source_filter="prediction_ledger"),
        "observed_mfe": _stats(ledger, "mfe_pct", source_filter="prediction_ledger"),
        "observed_mae": _stats(ledger, "mae_pct", source_filter="prediction_ledger"),
        "historical_workbook_proxy_separate": _stats(workbook, "proxy_return_pct", source_filter="historical_xlsx"),
        "segments": {
            "signal_score": _group_report(ledger, score_group),
            "projected_volume_ratio": _group_report(ledger, volume_group),
            "signal_time": _group_report(ledger, time_group),
            "signal_level": _group_report(ledger, lambda r: str(r.get("signal_level") or "UNKNOWN")),
        },
        "interpretation_guardrails": [
            "Only close_return_pct from prediction-ledger records is treated as a verified close outcome.",
            "Historical workbook proxy_return_pct is reported separately and is not execution P&L.",
            "UNKNOWN or missing outcomes are excluded from return denominators, not counted as losses.",
            "Wilson 95% intervals describe sample uncertainty; they are not forecasts or future win probabilities.",
            "Segment results are descriptive. No segment is promoted into Stage 0-3 selection rules by this report.",
            "MFE/MAE are observed-snapshot extrema, not guaranteed tick-level extrema.",
        ],
    }


def write_intelligence_reports(report: dict[str, Any], output_dir: Path) -> dict[str, str]:
    output_dir = Path(output_dir)
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"Output directory is not empty: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "strategy_intelligence.json"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    csv_path = output_dir / "strategy_segments.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        fields = ["dimension", "group", "sample_count", "positive_count", "negative_count",
                  "flat_count", "positive_rate_excluding_flat", "wilson_95_low",
                  "wilson_95_high", "mean_pct", "median_pct"]
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for dimension, groups in report["segments"].items():
            for group in groups:
                writer.writerow({"dimension": dimension, **group})

    md_path = output_dir / "strategy_intelligence.md"
    perf = report["verified_close_performance"]
    counts = report["record_counts"]
    lines = [
        "# 天機 3K 策略驗證研究報告",
        "",
        f"- 模式：`{report['mode']}`",
        f"- 訊號事件：{counts['prediction_ledger_events']}",
        f"- 有效收盤結果：{counts['verified_close_outcomes']}",
        f"- 未知／缺漏結果：{counts['ledger_outcomes_unknown']}",
        f"- Excel 歷史代理樣本：{counts['historical_workbook_rows']}（與正式收盤結果分開）",
        "",
        "## 正式 Ledger 收盤結果",
        "",
        f"- 正報酬：{perf['positive_count']}；負報酬：{perf['negative_count']}；持平：{perf['flat_count']}",
        f"- 排除持平後正報酬比例：{perf['positive_rate_excluding_flat']}",
        f"- 平均／中位報酬：{perf['mean_pct']}% / {perf['median_pct']}%",
        f"- Wilson 95% 區間：{perf['wilson_95_low']} ～ {perf['wilson_95_high']}",
        "",
        "## 分組觀察",
        "",
    ]
    for dimension, groups in report["segments"].items():
        lines.extend([f"### {dimension}", "", "| 分組 | 樣本 | 正 | 負 | 平 | 平均報酬% |",
                      "|---|---:|---:|---:|---:|---:|"])
        for g in groups:
            lines.append(f"| {g['group']} | {g['sample_count']} | {g['positive_count']} | {g['negative_count']} | {g['flat_count']} | {g['mean_pct']} |")
        lines.append("")
    lines.extend(["## 解讀限制", ""] + [f"- {x}" for x in report["interpretation_guardrails"]])
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    html_path = output_dir / "strategy_intelligence.html"
    cards = [
        ("Ledger 訊號", counts["prediction_ledger_events"]),
        ("有效收盤結果", counts["verified_close_outcomes"]),
        ("未知／缺漏", counts["ledger_outcomes_unknown"]),
        ("Excel 代理樣本", counts["historical_workbook_rows"]),
    ]
    card_html = "".join(
        f'<article class="card"><div class="muted">{html.escape(str(label))}</div><strong>{value}</strong></article>'
        for label, value in cards
    )
    tables = []
    for dimension, groups in report["segments"].items():
        rows_html = "".join(
            "<tr>" + "".join(
                f"<td>{html.escape(str(value if value is not None else '—'))}</td>"
                for value in (g["group"], g["sample_count"], g["positive_count"],
                              g["negative_count"], g["flat_count"], g["mean_pct"])
            ) + "</tr>"
            for g in groups
        )
        tables.append(
            f"<section><h2>{html.escape(dimension)}</h2><table><thead><tr>"
            "<th>分組</th><th>樣本</th><th>正</th><th>負</th><th>平</th><th>平均報酬%</th>"
            f"</tr></thead><tbody>{rows_html}</tbody></table></section>"
        )
    guardrails = "".join(f"<li>{html.escape(note)}</li>" for note in report["interpretation_guardrails"])
    html_doc = """<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>天機 3K 策略研究儀表板</title>
<style>
:root{color-scheme:light dark;font-family:system-ui,"Noto Sans TC",sans-serif}
body{margin:0;padding:24px;background:Canvas;color:CanvasText}
main{max-width:1100px;margin:auto}h1{margin-bottom:6px}.muted{opacity:.7}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin:22px 0}
.card,section{border:1px solid color-mix(in srgb,CanvasText 18%,transparent);border-radius:12px;padding:16px}
.card strong{display:block;font-size:28px;margin-top:8px}
table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:9px;border-bottom:1px solid color-mix(in srgb,CanvasText 15%,transparent)}
section{margin:16px 0;overflow-x:auto}li{margin:8px 0}.notice{padding:12px;border-left:4px solid #b7791f;background:color-mix(in srgb,#b7791f 10%,Canvas)}
</style></head><body><main>
<h1>天機 3K 策略研究儀表板</h1>
<p class="muted">離線唯讀分析｜不影響正式選股、MIS Radar 或 Telegram</p>
<div class="cards">""" + card_html + """</div>
<div class="notice">正式 Ledger 收盤樣本：""" + html.escape(str(perf["sample_count"])) + """；
排除持平後正報酬比例：""" + html.escape(str(perf["positive_rate_excluding_flat"])) + """。
代理報酬不與正式收盤結果混算。</div>
""" + "".join(tables) + """<section><h2>解讀限制</h2><ul>""" + guardrails + """</ul></section>
</main></body></html>"""
    html_path.write_text(html_doc, encoding="utf-8")
    return {"json": str(json_path), "csv": str(csv_path), "markdown": str(md_path), "html": str(html_path)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline read-only Tianji 3K strategy intelligence")
    parser.add_argument("--dataset", type=Path, required=True, help="shadow_validation_dataset.json")
    parser.add_argument("--output-dir", type=Path, required=True, help="New, empty output directory")
    args = parser.parse_args()
    dataset = json.loads(args.dataset.read_text(encoding="utf-8"))
    if not isinstance(dataset, list):
        raise ValueError("Dataset JSON must contain a list of normalized records")
    report = build_intelligence_report(dataset)
    outputs = write_intelligence_reports(report, args.output_dir)
    print(json.dumps({"report": report, "output_files": outputs}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
