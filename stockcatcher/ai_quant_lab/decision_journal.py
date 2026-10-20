"""V16 evidence-linked, deterministic six-Agent decision journal.

All conclusions are derived from recorded production events and explicit unknowns.
No production files are written and no broker/order action is possible here.
"""
from __future__ import annotations
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any
import json

AGENTS = {
    "cio": "天機總指揮", "quant": "量化研究員", "research": "產業研究員",
    "risk": "風控長", "execution": "交易執行員", "auditor": "驗證員",
}
VERSION = "v16.0"


def _present(v: Any) -> bool:
    return v is not None and v != "" and v != [] and v != {}


def _evidence(signal: dict[str, Any]) -> list[dict[str, Any]]:
    keys = [
        ("prediction_id", "正式版 prediction_id"), ("event_id", "正式版事件 ID"),
        ("source_path", "唯讀來源檔案"), ("created_at", "訊號時間"),
        ("current_price", "觸發快照價格"), ("up_pct", "快照漲幅"),
        ("projected_ratio", "預估量比"), ("live_volume_ratio", "即時量比"),
        ("signal_level", "訊號層級"), ("stage0_pass", "Stage 0 結果"),
        ("stage1_pass", "Stage 1 結果"), ("stage2_pass", "Stage 2 結果"),
        ("stage3_pass", "Stage 3 結果"), ("notification_status", "通知實際送達狀態"),
        ("validation_status", "驗證狀態"), ("ground_truth_3k", "3K Ground Truth"),
        ("validation_source_path", "驗證來源檔案"),
    ]
    return [{"field": k, "label": label, "value": signal.get(k)} for k, label in keys if _present(signal.get(k))]


def build_decision(signal: dict[str, Any]) -> dict[str, Any]:
    """Create role-specific findings; no fabricated fundamentals or future price path."""
    pid = str(signal.get("prediction_id") or "")
    if not pid:
        raise ValueError("prediction_id is required to create a traceable decision")
    evidence = _evidence(signal)
    missing = []
    if not signal.get("ground_truth_available"):
        missing.append("尚無可用 Ground Truth；不得宣稱預測命中或失敗")
    if not _present(signal.get("current_price")):
        missing.append("缺少觸發時價格快照")
    if not _present(signal.get("live_volume_ratio")) and not _present(signal.get("projected_ratio")):
        missing.append("缺少量能比資料")
    missing.extend(["尚未串接訊號後逐筆／5 分 K 路徑，MFE/MAE 未知", "未提供可核實的公司基本面／產業來源，本紀錄不做基本面斷言"])
    gt = signal.get("ground_truth_3k") if signal.get("ground_truth_available") else None
    notify = signal.get("notification_status")
    risk_flags = []
    if gt is None:
        risk_flags.append("VALIDATION_PENDING")
    if notify != "SENT":
        risk_flags.append("DELIVERY_NOT_CONFIRMED")
    if not _present(signal.get("current_price")):
        risk_flags.append("PRICE_SNAPSHOT_MISSING")
    if not _present(signal.get("live_volume_ratio")) and not _present(signal.get("projected_ratio")):
        risk_flags.append("VOLUME_EVIDENCE_MISSING")
    if signal.get("dynamic_candidate"):
        risk_flags.append("DYNAMIC_CANDIDATE_REQUIRES_CONFIRMATION")

    common = {"prediction_id": pid, "symbol": signal.get("symbol"), "name": signal.get("name"),
              "trade_date": signal.get("trade_date"), "signal_time": signal.get("created_at"),
              "evidence": evidence, "unknowns": missing, "source": "tianji_3k_read_only_audit",
              "source_path": signal.get("source_path"), "ground_truth_available": bool(signal.get("ground_truth_available")),
              "ground_truth_3k": gt, "read_only": True}
    findings = {
      "cio": ("彙整決策", "HOLD_FOR_EVIDENCE" if risk_flags else "REVIEW_REQUIRED", ["依現有正式訊號建立決策，不把通知送達視為預測正確。", *risk_flags], "等待行情路徑與驗證資料後再做策略結論。"),
      "quant": ("量化訊號審查", "SIGNAL_RECORDED", [f"訊號層級：{signal.get('signal_level') or '未知'}", f"Stage 0/1/2/3：{signal.get('stage0_pass')}/{signal.get('stage1_pass')}/{signal.get('stage2_pass')}/{signal.get('stage3_pass')}", f"預估量比：{signal.get('projected_ratio') if _present(signal.get('projected_ratio')) else '未知'}；即時量比：{signal.get('live_volume_ratio') if _present(signal.get('live_volume_ratio')) else '未知'}"], "取得訊號後 5 分 K 或逐筆資料，計算 MFE/MAE 與觸發後路徑。"),
      "research": ("產業與基本面查證", "EXTERNAL_RESEARCH_REQUIRED", ["本次正式訊號本身不包含可驗證的產業／財報證據。", "不以模型記憶補成公司事實。"], "需要時呼叫已配置的 MCP 研究工具，保留工具名稱、查詢參數、回傳摘要與查詢時間。"),
      "risk": ("風險審查", "BLOCK_AUTOMATED_ENTRY" if risk_flags else "MANUAL_REVIEW", risk_flags or ["現有欄位未顯示上述缺漏；仍須套用 Lab 部位與停損規則。"], "在價格、部位、停損、滑價與資料新鮮度齊備前，不自動建立紙上倉位。"),
      "execution": ("紙上執行審查", "NO_ORDER", ["V16 決策紀錄不會建立訂單。", "尚無可證明可成交的入場／出場路徑與滑價模型。"], "只有在獨立紙上交易風控流程通過後，才可另行建立模擬交易事件。"),
      "auditor": ("證據完整性稽核", "PASS_WITH_LIMITATIONS" if not missing else "INCOMPLETE_EVIDENCE", [f"通知狀態：{notify or '未記錄'}；Ground Truth：{'可用' if signal.get('ground_truth_available') else '不可用'}", *missing], "以 prediction_id 配對原始預測、驗證、通知與後續行情；不推算缺失結果。"),
    }
    agent_records = []
    for agent_id, (task, status, rationale, next_step) in findings.items():
        body = {**common, "agent_id": agent_id, "agent_name": AGENTS[agent_id], "task": task,
                "decision_status": status, "rationale": rationale, "next_step": next_step,
                "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "journal_version": VERSION}
        stable = json.dumps({k: v for k, v in body.items() if k != "created_at"}, ensure_ascii=False, sort_keys=True, default=str)
        body["decision_id"] = sha256(f"{VERSION}|{pid}|{agent_id}|{stable}".encode()).hexdigest()[:32]
        agent_records.append(body)
    return {"prediction_id": pid, "symbol": signal.get("symbol"), "name": signal.get("name"),
            "trade_date": signal.get("trade_date"), "signal_time": signal.get("created_at"),
            "agent_count": len(agent_records), "records": agent_records,
            "evidence_count": len(evidence), "unknowns": missing, "risk_flags": risk_flags,
            "source": "tianji_3k_read_only_audit", "read_only": True,
            "external_ai": {"gemini_used": False, "mcp_used": False,
                            "note": "外部 AI/MCP 尚未在此筆紀錄中執行；不會假裝已查證。"}}


def build_journal(audit: dict[str, Any], limit: int = 50) -> dict[str, Any]:
    signals = audit.get("signals") or []
    rows = [build_decision(s) for s in signals[:max(0, min(int(limit), 200))] if s.get("prediction_id")]
    return {"ok": True, "version": VERSION, "source_read_only": True,
            "signal_count": len(rows), "agent_record_count": sum(x["agent_count"] for x in rows),
            "ground_truth_available_count": sum(bool(x.get("records", [{}])[0].get("ground_truth_available")) for x in rows),
            "journals": rows,
            "limitations": ["這是證據導向的規則式 Agent 紀錄，不代表已呼叫 Gemini。", "MCP 查證必須有實際工具呼叫與回傳資料才可標記已查證。", "不會建立紙上訂單或連接券商。"]}
