"""Small standard-library HTTP API for local Lab dashboard; loopback only by default."""
from __future__ import annotations
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
import json, uuid, mimetypes, os, hashlib, threading, time, atexit
from pathlib import Path
from datetime import datetime
from env_loader import load_lab_env
ENV_STATUS = load_lab_env()
from engine import LabEngine
from autonomy import AutonomousLoop
from benchmarks import get_benchmarks
from historical_data import get_history
from event_adapter.signal_feed import TianjiSignalFeed
from event_adapter.audit import build_production_audit
from decision_journal import build_journal
from gemini_review import review_evidence
from event_adapter.production_reader import iter_production_events
from persistence_foundation import PersistenceFoundation, utcnow
from notification_dispatcher import DurableNotificationDispatcher
from backtest import run_backtest
from signal_validation import validate_signal_daily
import toalpha_mcp

ENGINE = LabEngine()
AUTONOMY = AutonomousLoop(ENGINE)
TIANJI_SIGNAL_FEED = TianjiSignalFeed()
DASHBOARD_DIST = Path(__file__).resolve().parent / "dashboard" / "dist"
PERSISTENCE = PersistenceFoundation(ENGINE.store)
PERSISTENCE_STATUS = {"ok": False, "durable": False, "status": "NOT_CONFIGURED"}
NOTIFICATION_DISPATCHER = DurableNotificationDispatcher(ENGINE.store)
if ENGINE.store.configured:
    try:
        if ENGINE.restore_error:
            raise RuntimeError(f"Initial durable state restore failed: {ENGINE.restore_error}")
        PERSISTENCE_STATUS = PERSISTENCE.start()
        if PERSISTENCE_STATUS.get("ok"):
            PERSISTENCE_STATUS["restore"] = PERSISTENCE.restore_into(ENGINE)
    except Exception as exc:
        PERSISTENCE_STATUS = {"ok": False, "durable": True, "status": "MIGRATION_OR_RECOVERY_ERROR",
                              "error": f"{type(exc).__name__}: {str(exc)[:300]}",
                              "warning": "請先套用 V17 migration 並確認 Supabase 權限；已禁止自主執行。"}

if PERSISTENCE_STATUS.get("ok") and PERSISTENCE.session_id:
    NOTIFICATION_DISPATCHER.start()  # no-op until Supabase + Telegram are configured

def _heartbeat_loop():
    while True:
        time.sleep(30)
        if PERSISTENCE.session_id and ENGINE.store.configured:
            try:
                rows = ENGINE.store.list_rows("ai_quant_lab_events", select="event_seq", order="event_seq.desc", limit=1)
                seq = int(rows[0]["event_seq"]) if rows else 0
                PERSISTENCE.heartbeat(seq)
                PERSISTENCE_STATUS["ok"] = True
                PERSISTENCE_STATUS["status"] = "RUNNING"
                PERSISTENCE_STATUS.pop("heartbeat_warning", None)
            except Exception:
                # Fail closed: stop new autonomous cycles when durable liveness cannot be proven.
                PERSISTENCE_STATUS["heartbeat_warning"] = "Supabase heartbeat failed; autonomy stopped and session may be recovered as stale after lease expiry."
                PERSISTENCE_STATUS["ok"] = False
                PERSISTENCE_STATUS["status"] = "DEGRADED_HEARTBEAT"
                try:
                    AUTONOMY.stop()
                except Exception:
                    pass
threading.Thread(target=_heartbeat_loop, daemon=True, name="lab-session-heartbeat").start()

def _close_session():
    try:
        NOTIFICATION_DISPATCHER.stop(timeout=3)
    except Exception:
        pass
    try:
        if PERSISTENCE.session_id:
            PERSISTENCE.close("CLOSED")
    except Exception:
        pass
atexit.register(_close_session)

def now(): return datetime.now().astimezone().isoformat(timespec="seconds")
class Handler(BaseHTTPRequestHandler):
    def _send(self, status, obj):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(status); self.send_header("Content-Type", "application/json; charset=utf-8"); self.send_header("Content-Length", str(len(body))); self.send_header("Access-Control-Allow-Origin", "http://127.0.0.1:5173"); self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS"); self.send_header("Access-Control-Allow-Headers", "Content-Type"); self.end_headers(); self.wfile.write(body)
    def do_OPTIONS(self): self._send(204, {})
    def do_GET(self):
        route = urlparse(self.path).path
        if route == "/":
            # Serve the actual Vue/Vite build when available. Keep the legacy standalone preview
            # as a backwards-compatible fallback until the frontend is built locally.
            built_index = DASHBOARD_DIST / "index.html"
            fallback = Path(__file__).resolve().parent / "preview.html"
            page = built_index if built_index.is_file() else fallback
            body = page.read_bytes()
            self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.send_header("Cache-Control", "no-cache"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
        elif route.startswith("/agents/"):
            # Serve only the six approved Agent sprites used by preview.html.
            name = route.rsplit("/", 1)[-1]
            allowed = {"cio-sprite.png", "quant-sprite.png", "research-sprite.png", "risk-sprite.png", "execution-sprite.png", "auditor-sprite.png"}
            if name not in allowed:
                self._send(404, {"error": "not found"}); return
            asset = Path(__file__).resolve().parent / "agents" / name
            if not asset.is_file():
                self._send(404, {"error": "agent asset missing"}); return
            body = asset.read_bytes()
            self.send_response(200); self.send_header("Content-Type", "image/png"); self.send_header("Cache-Control", "public, max-age=3600"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
        elif route == "/api/health": self._send(200, {"ok": True, "mode": "isolated-paper-only", "persistence": "supabase" if ENGINE.store.configured else "memory-only-dev", "supabase_configured": ENGINE.store.configured, "env_file_loaded": ENV_STATUS["loaded"], "market_provider": "Fugle" if ENV_STATUS["fugle_configured"] else "Yahoo Finance fallback", "provider_keys_configured": {k:v for k,v in ENV_STATUS.items() if k.endswith("_configured")}, "trade_chain_ready": bool(ENGINE.store.configured and ENV_STATUS["fugle_configured"] and ENV_STATUS["finmind_configured"]), "tianji_signal_path_exists": TIANJI_SIGNAL_FEED.source_root.is_dir(), "tianji_signal_path": str(TIANJI_SIGNAL_FEED.source_root), "ai_provider_configured": bool(os.getenv("OPENAI_API_KEY") or os.getenv("OPENAI_COMPATIBLE_API_KEY")), "gemini_configured": bool(os.getenv("GEMINI_API_KEY")), "persistence_v17": PERSISTENCE_STATUS} )
        elif route == "/api/agent-runs":
            if not ENGINE.store.configured:
                self._send(409, {"ok": False, "error": "Agent 執行狀態需要 Supabase。"})
                return
            query = parse_qs(urlparse(self.path).query)
            filters = {}
            if query.get("status"):
                filters["status"] = f"eq.{query['status'][0]}"
            rows = ENGINE.store.list_rows("ai_quant_lab_agent_runs", select="*", order="updated_at.desc", limit=100, filters=filters)
            self._send(200, {"ok": True, "runs": rows, "count": len(rows)})
        elif route == "/api/notifications/status":
            status = NOTIFICATION_DISPATCHER.status()
            self._send(200 if status.get("ok") else 503, status)
        elif route == "/api/persistence":
            checkpoint = None
            try:
                checkpoint = PERSISTENCE.latest_valid_checkpoint() if ENGINE.store.configured else None
            except Exception as exc:
                self._send(503, {"ok": False, "persistence": PERSISTENCE_STATUS, "error": str(exc)[:240]})
                return
            self._send(200, {"ok": bool(PERSISTENCE_STATUS.get("ok") and not ENGINE.persistence_degraded and not ENGINE.restore_error), "session_id": PERSISTENCE.session_id,
                             "parent_session_id": PERSISTENCE.parent_session_id, "persistence": PERSISTENCE_STATUS,
                             "latest_checkpoint": ({"checkpoint_id": checkpoint.get("checkpoint_id"),
                                                    "checkpoint_seq": checkpoint.get("checkpoint_seq"),
                                                    "last_event_seq": checkpoint.get("last_event_seq"),
                                                    "created_at": checkpoint.get("created_at")} if checkpoint else None),
                             "paper_only": True, "production_write": False})
        elif route == "/api/state":
            auto = AUTONOMY.status(); marks = {q["symbol"]: q["price"] for q in auto["market"]}
            state = ENGINE.state(marks); state["autonomy"] = {k:v for k,v in auto.items() if k != "market"}; state["market"] = auto["market"]
            state["persistence_v17"] = {"status": PERSISTENCE_STATUS.get("status"), "ok": bool(PERSISTENCE_STATUS.get("ok")),
                                         "session_id": PERSISTENCE.session_id, "parent_session_id": PERSISTENCE.parent_session_id,
                                         "restore_error": ENGINE.restore_error, "engine_persistence_degraded": ENGINE.persistence_degraded}
            self._send(200, state)
        elif route == "/api/market": self._send(200, AUTONOMY.status())
        elif route == "/api/production/signals": self._send(200, TIANJI_SIGNAL_FEED.scan())
        elif route == "/api/production/audit":
            since = parse_qs(urlparse(self.path).query).get("since", [None])[0]
            try: self._send(200, build_production_audit(TIANJI_SIGNAL_FEED.source_root, since=since))
            except Exception as exc: self._send(502, {"ok":False, "error":f"正式版訊號稽核失敗：{type(exc).__name__}: {exc}", "source_root":str(TIANJI_SIGNAL_FEED.source_root)})
        elif route == "/api/production/decisions":
            query = parse_qs(urlparse(self.path).query)
            since = query.get("since", [None])[0]
            try:
                audit = build_production_audit(TIANJI_SIGNAL_FEED.source_root, since=since)
                limit = int(query.get("limit", [50])[0])
                self._send(200, build_journal(audit, limit=limit))
            except Exception as exc:
                self._send(502, {"ok":False, "error":f"六 Agent 決策紀錄建立失敗：{type(exc).__name__}: {exc}"})
        elif route == "/api/benchmarks": self._send(200, get_benchmarks())
        elif route == "/api/market/history":
            symbol = parse_qs(urlparse(self.path).query).get('symbol', [''])[0]
            try: self._send(200, get_history(symbol))
            except Exception as exc: self._send(502, {'error': str(exc), 'symbol': symbol})
        elif route == "/api/research/tools":
            try: self._send(200, {'endpoint':'https://toalpha.tw/mcp','tools':toalpha_mcp.list_tools()})
            except Exception as exc: self._send(502, {'error': str(exc), 'tools':[]})
        elif route == "/api/backtest":
            symbol = parse_qs(urlparse(self.path).query).get("symbol", [""])[0]
            try:
                history = get_history(symbol, limit=520)
                report = run_backtest(symbol, history.get("candles", []))
                report["data_source"] = history.get("source")
                report["data_through"] = history.get("latest_date")
                if report.get("ok"):
                    report["persistence"] = "supabase" if ENGINE.store.configured else "memory-only-dev"
                    if ENGINE.store.configured:
                        ENGINE.store.record_report(f"backtest-{symbol}-{report['last_date']}", report['last_date'], report)
                self._send(200 if report.get("ok") else 422, {"ok": bool(report.get("ok")), "report": report})
            except Exception as exc:
                self._send(502, {"ok": False, "error": f"回測資料取得失敗：{type(exc).__name__}: {exc}"})
        elif route == "/api/report":
            date = parse_qs(urlparse(self.path).query).get("date", [None])[0]
            date=date or now()[:10]
            report=ENGINE.generate_report(date)
            self._send(200, {"ok": True, "report": report, "persistence": report.get("persistence", "memory-only-dev")})
        elif DASHBOARD_DIST.is_dir():
            # Serve hashed Vite assets (JS/CSS), the watercolor office background, and
            # other public files from the same origin as the API.
            relative = route.lstrip("/") or "index.html"
            target = (DASHBOARD_DIST / relative).resolve()
            if target.is_file() and target.is_relative_to(DASHBOARD_DIST.resolve()):
                body = target.read_bytes()
                content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
                if content_type.startswith("text/") or content_type in ("application/javascript", "application/json", "image/svg+xml"):
                    content_type += "; charset=utf-8"
                self.send_response(200); self.send_header("Content-Type", content_type); self.send_header("Cache-Control", "public, max-age=3600"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
            else: self._send(404, {"error": "not found"})
        else: self._send(404, {"error": "not found"})
    def do_POST(self):
        route = urlparse(self.path).path
        try:
            length = int(self.headers.get("Content-Length", "0")); payload = json.loads(self.rfile.read(length) or b"{}")
            if route.startswith("/api/notifications/") and route.endswith("/retry"):
                if not ENGINE.store.configured or not PERSISTENCE_STATUS.get("ok"):
                    self._send(409, {"ok": False, "error": "持久化未就緒，拒絕重試通知。"}); return
                outbox_id = route.split("/")[-2]
                row = ENGINE.store.get_outbox(outbox_id)
                if not row:
                    self._send(404, {"ok": False, "error": "找不到通知工作。"}); return
                if row.get("status") != "DEAD_LETTER":
                    self._send(409, {"ok": False, "error": "僅允許人工重試 DEAD_LETTER；UNKNOWN 必須先人工對帳，避免重複通知。", "status": row.get("status")}); return
                ENGINE.store.update_outbox(outbox_id, {"status":"RETRY_PENDING", "attempts":0, "available_at":utcnow(),
                    "dead_lettered_at":None, "last_error":None, "updated_at":utcnow()}, expected_status="DEAD_LETTER")
                self._send(200, {"ok": True, "outbox_id": outbox_id, "status":"RETRY_PENDING", "manual_retry":True})
            elif route == "/api/agent-runs/start":
                if not PERSISTENCE_STATUS.get("ok") or not PERSISTENCE.session_id:
                    self._send(409, {"ok": False, "error": "V17 Session 未就緒，無法建立持久化 Agent Run。", "persistence": PERSISTENCE_STATUS})
                    return
                agent_id = str(payload.get("agent_id") or "")
                task_type = str(payload.get("task_type") or "").strip()
                idem = str(payload.get("idempotency_key") or "").strip()
                if not task_type or not idem:
                    self._send(400, {"ok": False, "error": "task_type 與 idempotency_key 必填。"})
                    return
                result = PERSISTENCE.begin_agent_run(agent_id, task_type, idempotency_key=idem,
                    prediction_id=payload.get("prediction_id"), input_event_ids=payload.get("input_event_ids") or [])
                self._send(201, {"ok": True, **result})
            elif route.startswith("/api/agent-runs/") and route.endswith("/finish"):
                if not PERSISTENCE_STATUS.get("ok"):
                    self._send(409, {"ok": False, "error": "V17 Session 未就緒。"})
                    return
                run_id = route.split("/")[-2]
                result = PERSISTENCE.finish_agent_run(run_id, str(payload.get("status") or "COMPLETED"),
                                                      result=payload.get("result") or {}, error=payload.get("error"))
                self._send(200, {"ok": True, **result})
            elif route == "/api/persistence/checkpoint":
                if not PERSISTENCE_STATUS.get("ok") or not PERSISTENCE.session_id:
                    self._send(409, {"ok": False, "error": "V17 持久化 Session 未就緒；已拒絕建立假檢查點。", "status": PERSISTENCE_STATUS})
                    return
                rows = ENGINE.store.list_rows("ai_quant_lab_events", select="event_seq", order="event_seq.desc", limit=1)
                last_seq = int(rows[0]["event_seq"]) if rows else 0
                snapshot = {"roles": ENGINE.state().get("roles", []), "created_at": utcnow(),
                            "paper_ledger_rebuilt_from_trades": True, "event_count_in_memory": len(ENGINE.events)}
                result = PERSISTENCE.create_checkpoint(snapshot, last_seq)
                self._send(201, {"ok": True, **result, "paper_orders_created": 0})
            elif route == "/api/persistence/heartbeat":
                if not PERSISTENCE_STATUS.get("ok") or not PERSISTENCE.session_id:
                    self._send(409, {"ok": False, "error": "V17 持久化 Session 未就緒。"})
                    return
                rows = ENGINE.store.list_rows("ai_quant_lab_events", select="event_seq", order="event_seq.desc", limit=1)
                seq = int(rows[0]["event_seq"]) if rows else 0
                self._send(200, {"ok": True, **PERSISTENCE.heartbeat(seq)})
            elif route == "/api/production/validate-signal":
                # Read-only production signal validation; report persistence is Lab-owned only.
                symbol = str(payload.get("symbol") or "").strip().upper()
                signal_date = str(payload.get("signal_date") or "").strip()
                signal_price = payload.get("signal_price")
                if not symbol or not signal_date or signal_price is None:
                    raise ValueError("symbol、signal_date、signal_price 必填")
                if not symbol.isalnum() or len(symbol) > 10:
                    raise ValueError("symbol 格式不正確")
                history = get_history(symbol, limit=520)
                report = validate_signal_daily(symbol, signal_date, signal_price, history.get("candles", []),
                                               horizon_days=payload.get("horizon_days", 7),
                                               stop_loss_pct=payload.get("stop_loss_pct", 2.0))
                report["data_source"] = history.get("source")
                report["history_latest_date"] = history.get("latest_date")
                report["evidence_policy"] = "production source read-only; daily candles only; no order generated"
                report["persistence"] = "not_persisted"
                if report.get("ok") and ENGINE.store.configured:
                    saved = ENGINE.store.record_research_report(
                        report_key=f"signal-validation-{symbol}-{signal_date}-daily-v1",
                        report_date=report.get("observation_end") or signal_date,
                        title=f"訊號事後驗證 {symbol} · {signal_date}",
                        summary=f"日 K 觀察 {report.get('actual_horizon_trading_days', 0)} 根；僅研究驗證，不建立訂單。",
                        report_type="SIGNAL_POST_VALIDATION", report=report)
                    report["persistence"] = saved.get("table", "supabase")
                elif not ENGINE.store.configured:
                    report["persistence_warning"] = "Supabase 未設定；本次結果只回傳畫面，未聲稱已持久化。"
                self._send(200 if report.get("ok") else 422, {"ok": bool(report.get("ok")), "report": report})
            elif route == "/api/production/decisions/generate":
                if not ENGINE.store.configured:
                    self._send(409, {"ok":False, "error":"Supabase 尚未設定；已阻止決策紀錄只存在記憶體。", "paper_orders_created":0})
                    return
                audit = build_production_audit(TIANJI_SIGNAL_FEED.source_root, since=payload.get("since"))
                journal = build_journal(audit, limit=payload.get("limit", 50))
                outcome = {"persisted":0, "duplicates":0, "errors":0}
                for item in journal["journals"]:
                    for record in item["records"]:
                        event = {"event_id": f"decision:{record['decision_id']}", "event_type":"agent.decision_recorded",
                                 "occurred_at":record["created_at"], "source":"ai_quant_lab_v16_decision_journal",
                                 "payload":record}
                        result = ENGINE.process(event)
                        if result.get("status") == "processed": outcome["persisted"] += 1
                        elif result.get("status") == "duplicate": outcome["duplicates"] += 1
                        else: outcome["errors"] += 1
                journal.update(outcome)
                journal.update({"ok":outcome["errors"] == 0, "persistence":"supabase", "paper_orders_created":0,
                                "source_read_only":True, "external_ai_used":False})
                self._send(200 if journal["ok"] else 207, journal)
            elif route == "/api/production/import":
                if not ENGINE.store.configured:
                    self._send(409, {"ok":False, "error":"Supabase 尚未設定；已阻止匯入，避免稽核紀錄只留在記憶體。"})
                    return
                audit = build_production_audit(TIANJI_SIGNAL_FEED.source_root, since=payload.get("since"))
                if not audit.get("ok"):
                    self._send(502, {"ok":False, "error":"無法建立正式版訊號稽核"})
                    return
                outcomes = {"imported_predictions":0, "imported_validations":0, "duplicates":0, "errors":0}
                for event in iter_production_events(TIANJI_SIGNAL_FEED.source_root, since=payload.get("since")):
                    if event.get("event_type") == "prediction.recorded":
                        outcomes_key = "imported_predictions"
                    elif event.get("event_type") == "prediction.validated":
                        outcomes_key = "imported_validations"
                    else:
                        continue
                    result = ENGINE.process(event)
                    if result.get("status") == "processed": outcomes[outcomes_key] += 1
                    elif result.get("status") == "duplicate": outcomes["duplicates"] += 1
                    else: outcomes["errors"] += 1
                outcomes.update({"ok": outcomes["errors"] == 0, "persistence":"supabase", "source_read_only":True, "paper_orders_created":0, "audit_summary":{k:audit.get(k) for k in ("prediction_count","validated_count","ground_truth_available_count","ground_truth_missing_count")}})
                self._send(200 if outcomes["ok"] else 207, outcomes)
            elif route == "/api/autonomy/start":
                if not ENGINE.store.configured or not PERSISTENCE_STATUS.get("ok") or not PERSISTENCE.session_id or ENGINE.persistence_degraded or ENGINE.restore_error:
                    self._send(409, {"started": False, "error": "V17 持久化未就緒；已阻止自主執行。請先套用 migration 並確認 Session、心跳及恢復流程正常。", "persistence": PERSISTENCE_STATUS})
                else:
                    self._send(200, AUTONOMY.start())
            elif route == "/api/autonomy/stop":
                self._send(200, AUTONOMY.stop())
            elif route == "/api/autonomy/scan-once":
                if not ENGINE.store.configured or not PERSISTENCE_STATUS.get("ok") or not PERSISTENCE.session_id or ENGINE.persistence_degraded or ENGINE.restore_error:
                    self._send(409, {"error": "V17 持久化未就緒；已阻止可能產生模擬成交的掃描。", "persistence": PERSISTENCE_STATUS})
                else:
                    self._send(200, AUTONOMY.run_once())
            elif route == "/api/agents/gemini-review-validation":
                if not ENGINE.store.configured or not PERSISTENCE_STATUS.get("ok") or not PERSISTENCE.session_id or ENGINE.persistence_degraded or ENGINE.restore_error:
                    self._send(409, {"ok":False, "error":"V17 持久化未就緒；為避免覆核只存在記憶體，已阻止 Gemini 事後覆核留存。", "persistence":PERSISTENCE_STATUS})
                    return
                report = payload.get("validation_report")
                if not isinstance(report, dict) or not report.get("ok"):
                    raise ValueError("validation_report 必須是已完成的事後驗證報告")
                if str(report.get("symbol")) != "6278" or str(report.get("signal_date")) != "2026-10-07":
                    raise ValueError("此版本的二次覆核僅接受已核對的台表科 6278 / 2026-10-07 案例")
                packet = {"review_type":"POST_SIGNAL_VALIDATION_REVIEW", "original_signal":{"symbol":"6278","signal_date":"2026-10-07","reference_price":250.5,"signal_level":"STRONG (as reported by user-provided evidence; not independently re-derived)"},
                          "validation_report":report,
                          "review_rules":["區分日 K 描述性 MFE/MAE 與可實現交易報酬", "不可把日 K 高低點視為已成交價格", "明確說明日 K 無法判斷盤中觸發先後", "不得覆寫原始 Gemini 覆核、Ground Truth 或風控決策", "缺少 5 分 K 時不得聲稱已驗證盤中突破策略"]}
                result = review_evidence(packet)
                evidence_id = hashlib.sha256(f"gemini-post-validation|6278|2026-10-07|{result['evidence_packet_hash']}".encode()).hexdigest()[:32]
                stored = {"evidence_id":evidence_id,"agent_id":"research","agent_name":"Gemini 事後驗證覆核","provider":result["provider"],"model":result["model"],
                          "prediction_id":"6278-2026-10-07-daily-validation","symbol":"6278","evidence_packet_hash":result["evidence_packet_hash"],
                          "review":result["review"],"authority":"advisory_only","warning":result["warning"],"occurred_at":now(),"read_only":True}
                ev = {"event_id":f"external-evidence:{evidence_id}","event_type":"agent.research_evidence_recorded","occurred_at":stored["occurred_at"],"source":"gemini_post_validation_review","payload":stored}
                persisted = ENGINE.process(ev)
                if persisted.get("status") not in ("processed", "duplicate") or persisted.get("persistence") not in ("supabase", "durable"):
                    self._send(503, {"ok":False,"error":"Gemini 有回覆，但覆核紀錄未能確認持久化；不可視為完成。","evidence_id":evidence_id,"journal_status":persisted.get("status"),"journal_persistence":persisted.get("persistence")})
                    return
                self._send(200, {"ok":True, **result, "evidence_id":evidence_id,"journal_persistence":persisted.get("persistence"),"journal_status":persisted.get("status"),"paper_orders_created":0,"original_review_overwritten":False})
            elif route == "/api/agents/gemini-review":
                pid = str(payload.get("prediction_id") or "").strip()
                if not pid: raise ValueError("prediction_id 必填")
                audit = build_production_audit(TIANJI_SIGNAL_FEED.source_root, since=payload.get("since"))
                signal = next((x for x in audit.get("signals", []) if str(x.get("prediction_id")) == pid), None)
                if not signal: raise ValueError("找不到指定 prediction_id；請先確認正式版訊號資料目錄")
                packet = build_journal({"signals":[signal]}, limit=1)["journals"][0]
                result = review_evidence(packet)
                evidence_id = hashlib.sha256(f"gemini|{pid}|{result['evidence_packet_hash']}".encode()).hexdigest()[:32]
                stored = {"evidence_id":evidence_id,"agent_id":str(payload.get("agent") or "research"),
                          "agent_name":"Gemini 研究覆核","provider":result["provider"],"model":result["model"],
                          "prediction_id":pid,"symbol":signal.get("symbol"),"evidence_packet_hash":result["evidence_packet_hash"],
                          "review":result["review"],"authority":result["authority"],"warning":result["warning"],
                          "occurred_at":now(),"read_only":True}
                ev = {"event_id":f"external-evidence:{evidence_id}","event_type":"agent.research_evidence_recorded",
                      "occurred_at":stored["occurred_at"],"source":"gemini_evidence_review","payload":stored}
                persisted = ENGINE.process(ev)
                self._send(200, {"ok":True, **result, "evidence_id":evidence_id,
                                 "journal_persistence":persisted.get("persistence", "memory-only-dev"),
                                 "journal_status":persisted.get("status"), "paper_orders_created":0})
            elif route in {"/api/research/call", "/api/agents/research"}:
                tool = str(payload.get('tool') or '')
                arguments = payload.get('arguments') or {}
                agent = str(payload.get('agent') or 'research') if route == '/api/agents/research' else 'research'
                agent_names = {'cio':'天機總指揮','quant':'量化研究員','research':'產業研究員','risk':'風控長','execution':'交易執行員','auditor':'驗證員'}
                if agent not in agent_names: raise ValueError('未知 Agent')
                if not tool: raise ValueError('必須指定研究工具')
                if not isinstance(arguments, dict): raise ValueError('arguments 必須是 JSON object')
                ENGINE.agent_task(agent, 'working', f'調用 ToAlpha 研究工具：{tool[:90]}')
                try:
                    result = toalpha_mcp.call_tool(tool, arguments)
                    ENGINE.agent_task(agent, 'success', f'研究工具完成：{tool[:90]}')
                    # Persist an auditable evidence envelope in the Lab ledger; never write to production.
                    raw_result = json.dumps(result, ensure_ascii=False, default=str)
                    evidence_id = hashlib.sha256(json.dumps({'tool':tool,'arguments':arguments,'result':raw_result},ensure_ascii=False,sort_keys=True).encode()).hexdigest()[:32]
                    evidence_payload = {'evidence_id':evidence_id,'agent_id':agent,'agent_name':agent_names[agent],
                        'provider':'ToAlpha MCP','endpoint':'https://toalpha.tw/mcp','tool':tool,
                        'arguments':arguments,'result':result if len(raw_result) <= 24000 else {'truncated':True,'preview':raw_result[:22000], 'original_chars':len(raw_result)},
                        'result_sha256':hashlib.sha256(raw_result.encode()).hexdigest(),'occurred_at':now(),
                        'read_only':True,'authority':'external_source_result_not_model_verified'}
                    evidence_event={'event_id':f'external-evidence:{evidence_id}','event_type':'agent.research_evidence_recorded',
                        'occurred_at':evidence_payload['occurred_at'],'source':'toalpha_mcp','payload':evidence_payload}
                    persisted=ENGINE.process(evidence_event)
                    self._send(200, {'ok': True, 'agent': agent, 'agent_name': agent_names[agent], 'tool': tool, 'result': result,
                        'endpoint': 'https://toalpha.tw/mcp','evidence_id':evidence_id,
                        'journal_persistence':persisted.get('persistence','memory-only-dev'),'journal_status':persisted.get('status'),
                        'result_sha256':evidence_payload['result_sha256']})
                except Exception as exc:
                    ENGINE.agent_task(agent, 'warning', f'研究工具失敗：{str(exc)[:120]}')
                    raise
            elif route == "/api/events":
                if not isinstance(payload, dict): raise ValueError("JSON body must be an object")
                event = {"event_id": payload.get("event_id") or str(uuid.uuid4()), "event_type": payload.get("event_type"), "occurred_at": payload.get("occurred_at") or now(), "source": "dashboard-local", "payload": payload.get("payload", {})}
                outcome=ENGINE.process(event)
                self._send(200, outcome)
            elif route == "/api/demo":
                event = {"event_id": str(uuid.uuid4()), "event_type": "signal.created", "occurred_at": now(), "source": "dashboard-demo", "payload": {"mode": "paper", "symbol": str(payload.get("symbol", "2330")), "side": str(payload.get("side", "BUY")).upper(), "quantity": int(payload.get("quantity", 100)), "price": str(payload.get("price", "100"))}}
                outcome=ENGINE.process(event)
                self._send(200, outcome)
            else: self._send(404, {"error": "not found"})
        except Exception as exc: self._send(400, {"error": str(exc)})
    def log_message(self, fmt, *args): print("[Lab API] " + fmt % args)

if __name__ == "__main__":
    host, port = "127.0.0.1", 8765
    print(f"Tianji AI Quant Lab API: http://{host}:{port} (loopback only; paper trading only)")
    print(f"[Lab config] env_file_loaded={ENV_STATUS['loaded']} supabase_configured={ENV_STATUS['supabase_configured']} fugle_key={ENV_STATUS['fugle_configured']} finmind_key={ENV_STATUS['finmind_configured']} telegram_keys={ENV_STATUS['telegram_configured']} (secret values never logged)")
    ThreadingHTTPServer((host, port), Handler).serve_forever()
