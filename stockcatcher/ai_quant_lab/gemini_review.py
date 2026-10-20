"""Optional Gemini critique of a fixed evidence packet; never an execution authority."""
from __future__ import annotations
import json, os, urllib.request, urllib.error
from typing import Any


def review_evidence(packet: dict[str, Any], timeout: int = 20) -> dict[str, Any]:
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("Gemini 未設定；請在本機 .env 設定 GEMINI_API_KEY 後重啟 Lab。")
    model = os.getenv("GEMINI_MODEL", "gemini-3.8-flash").strip() or "gemini-2.5-flash"
    prompt = """你是 AI Quant Lab 的研究覆核者，不是交易執行器。只能依照提供的 JSON 證據包評論。
不得補造行情、財報、法人籌碼、新聞、命中率、MFE/MAE；缺資料必須列入 unknowns。
不得把通知送達等同預測正確。不得下單或要求忽略風控。輸出繁體中文 JSON，欄位為：
summary (string), evidence_supported_points (array of strings), hypotheses_not_verified (array of strings), missing_evidence (array of strings), contradictions_or_risks (array of strings), suggested_checks (array of strings), confidence (LOW|MEDIUM|HIGH)。
confidence 只能反映本證據包的完整度，不能表示報酬保證。原始證據包：\n""" + json.dumps(packet, ensure_ascii=False, default=str)[:18000]
    body = json.dumps({"contents":[{"parts":[{"text":prompt}]}], "generationConfig":{"responseMimeType":"application/json","temperature":0.1}}, ensure_ascii=False).encode()
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
    req = urllib.request.Request(url, data=body, headers={"Content-Type":"application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # Do not leak the credential-bearing URL or response headers.
        raise RuntimeError(f"Gemini API HTTP {exc.code}") from exc
    except Exception as exc:
        raise RuntimeError(f"Gemini 呼叫失敗：{type(exc).__name__}") from exc
    candidates = raw.get("candidates") or []
    parts = ((candidates[0].get("content") or {}).get("parts") or []) if candidates else []
    text = "\n".join(str(p.get("text", "")) for p in parts).strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Gemini 回傳不是可解析的 JSON；未將結果當作查證結論") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError("Gemini 回傳格式不符合預期")
    return {"provider":"Gemini", "model":model, "review":parsed,
            "authority":"advisory_only", "evidence_packet_hash":__import__('hashlib').sha256(json.dumps(packet,ensure_ascii=False,sort_keys=True,default=str).encode()).hexdigest(),
            "warning":"Gemini 輸出是研究覆核意見，不是獨立事實來源；需由 MCP/原始資料驗證，且不能覆蓋硬性風控。"}
