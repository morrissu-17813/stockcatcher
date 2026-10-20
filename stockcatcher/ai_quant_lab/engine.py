"""Isolated in-memory development engine. Supabase will be the only durable store."""
from __future__ import annotations
import json, uuid, copy, threading
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from paper_trading.ledger import PaperLedger
from supabase_store import SupabaseStore
from execution_safety import market_data_block_reason, exit_trigger

ROOT = Path(__file__).resolve().parent
ROLE_DEFS = {
    "cio": ("天機總指揮", "CIO"), "quant": ("量化研究員", "QUANT"),
    "research": ("產業研究員", "RESEARCH"), "risk": ("風控長", "RISK"),
    "execution": ("交易執行員", "EXECUTION"), "auditor": ("驗證員", "AUDITOR"),
}

class LabEngine:
    """In-memory event processor for UI development; never connects to broker or production writes."""
    def __init__(self, db_path=None, initial_cash: Decimal = Decimal("1000000"), fee_rate: Decimal = Decimal("0.001425"), max_order_notional: Decimal = Decimal("100000"), store=None):
        # db_path is accepted for backward compatibility only; it is never opened.
        self._state_lock = threading.RLock()
        self.initial_cash = Decimal(initial_cash); self.fee_rate = Decimal(fee_rate); self.max_order_notional = Decimal(max_order_notional)
        self.store = store or SupabaseStore()
        self.ledger = PaperLedger(self.initial_cash, self.fee_rate)
        self.events: list[dict[str, Any]] = []; self.event_ids: set[str] = set(); self.roles = {}
        default_zones = {"cio":"COMMAND_CENTER", "quant":"ANALYST_DESKS", "research":"ANALYST_DESKS", "risk":"RISK_OFFICE", "execution":"TRADING_DESK", "auditor":"AUDIT_STATION"}
        for rid, (name, role) in ROLE_DEFS.items(): self.roles[rid] = {"role_id":rid,"name":name,"role":role,"status":"idle","task":"等待事件","updated_at":self._now(),"target_zone":default_zones[rid],"bubble":""}
        self.restore_error = None
        self.persistence_degraded = False
        self.recovery_summary = {"status": "NOT_REQUIRED" if not self.store.configured else "PENDING", "restored_trade_rows": 0, "restored_fills": 0, "restored_open_positions": 0, "restored_event_ids": 0, "last_event_seq": 0, "error": None}
        if self.store.configured:
            try:
                self._restore_from_supabase()
            except Exception as exc:
                # Keep the read-only UI available, but V17 startup recovery will fail closed
                # and block autonomy until the durable schema and restore path are healthy.
                self.restore_error = f"{type(exc).__name__}: {str(exc)[:300]}"
                self.recovery_summary.update({"status": "FAILED", "error": self.restore_error})

    def _restore_from_supabase(self):
        """Rebuild paper positions/cash from durable Supabase rows; never reads local DB/files."""
        # PostgREST deployments commonly cap responses at 1,000 rows; page through all fills
        # so the paper account does not silently lose older positions after long use.
        rows = []
        offset = 0
        page_size = 1000
        while True:
            # Stable tie-breakers prevent same-market-timestamp fills replaying arbitrarily.
            page = self.store.list_rows('ai_quant_lab_paper_trades', select='trade_key,symbol,side,quantity,price,fees,status,executed_at,created_at', order='executed_at.asc,created_at.asc,trade_key.asc', limit=page_size, offset=offset)
            rows.extend(page)
            if len(page) < page_size:
                break
            offset += page_size
        seen_trade_keys = set()
        filled_rows = 0
        for row in rows:
            if row.get('status') != 'FILLED':
                continue
            trade_key = str(row.get('trade_key') or row.get('idempotency_key') or '')
            if trade_key and trade_key in seen_trade_keys:
                raise RuntimeError(f"duplicate persisted paper trade key during restore: {trade_key}")
            if trade_key: seen_trade_keys.add(trade_key)
            missing = [field for field in ('symbol','side','quantity','price') if row.get(field) is None]
            if missing: raise RuntimeError(f"persisted paper trade missing required fields: {','.join(missing)}")
            self.ledger.execute(row['symbol'], row['side'], int(row['quantity']), Decimal(str(row['price'])), fee_override=Decimal(str(row.get('fees') or '0')))
            filled_rows += 1
        if self.ledger.cash < 0 or any(p.quantity < 0 for p in self.ledger.positions.values()):
            raise RuntimeError("restored paper ledger violates cash/position invariants")
        self.recovery_summary.update({"restored_trade_rows": len(rows), "restored_fills": filled_rows, "restored_open_positions": sum(1 for p in self.ledger.positions.values() if p.quantity > 0)})
        all_event_ids = set()
        recent_events = []
        max_event_seq = 0
        offset = 0
        page_size = 1000
        while True:
            page = self.store.list_rows('ai_quant_lab_events', select='event_key,event_type,source,occurred_at,payload,created_at,event_seq', order='event_seq.desc', limit=page_size, offset=offset)
            if not page:
                break
            for row in page:
                key = row.get('event_key')
                if not key:
                    continue
                all_event_ids.add(str(key))
                try: max_event_seq = max(max_event_seq, int(row.get('event_seq') or 0))
                except (TypeError, ValueError): pass
                if len(recent_events) < 500:
                    envelope = row.get('payload') or {}
                    original_event = envelope.get('event') or {}
                    outcome = envelope.get('outcome') or {}
                    recent_events.append({
                        'event_id': str(key), 'event_type': row.get('event_type', 'unknown'),
                        'event_seq': row.get('event_seq'), 'occurred_at': row.get('occurred_at') or '',
                        'source': row.get('source', 'supabase'), 'status': outcome.get('status', 'restored'),
                        'result': outcome, 'processed_at': row.get('created_at', ''),
                        'payload': original_event.get('payload', {})
                    })
            if len(page) < page_size:
                break
            offset += len(page)
        self.event_ids.update(all_event_ids)
        self.events = recent_events
        self.recovery_summary.update({"status": "RESTORED", "restored_event_ids": len(all_event_ids), "last_event_seq": max_event_seq, "error": None})

    @staticmethod
    def _now(): return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    def _set_role(self, rid, status, task):
        """Update an Agent's real runtime state and publish a durable movement event.

        Movement is a projection of real backend task transitions, not a trade signal.
        Agent motion events use the existing ai_quant_lab_events table; no new table,
        production-module import, broker connection, or frontend secret is introduced.
        """
        if rid not in self.roles:
            return
        role = self.roles[rid]
        task_text = str(task or "")[:240]
        # The destination reflects the role's actual work area; warning/success states
        # move the character to a shared review point instead of looping decorative motion.
        base_zone = {
            "cio": "COMMAND_CENTER", "quant": "ANALYST_DESKS",
            "research": "ANALYST_DESKS", "risk": "RISK_OFFICE",
            "execution": "TRADING_DESK", "auditor": "AUDIT_STATION",
        }.get(rid, "COMMAND_CENTER")
        task_lower = task_text.lower()
        if any(token in task_lower for token in ("茶水", "茶歇", "咖啡", "休息", "coffee", "break")):
            zone = "COFFEE_CORNER"
        else:
            zone = "RISK_OFFICE" if status == "warning" else ("DEBATE_TABLE" if status == "success" else base_zone)
        changed = role.get("status") != status or role.get("task") != task_text or role.get("target_zone") != zone
        role.update(status=status, task=task_text, updated_at=self._now(), target_zone=zone,
                    bubble=task_text if status in ("working", "warning", "success") else "")
        if not changed or not self.store.configured:
            return
        event_id = f"agent-state-{uuid.uuid4()}"
        event = {"event_id": event_id, "event_type": "agent.state_changed", "occurred_at": role["updated_at"],
                 "source": "ai_quant_lab_runtime", "payload": {"agent_id": rid, "agent_role": role.get("role"),
                 "status": status, "task": task_text, "target_zone": zone, "bubble": role["bubble"]}}
        try:
            self.store.record_event(event, {"status": "processed", "actions": ["agent_state_published"],
                                            "agent_id": rid, "target_zone": zone})
        except Exception as exc:
            # A visualization telemetry write must never interrupt or bypass trade safety.
            role["telemetry_warning"] = str(exc)[:160]

    def agent_task(self, rid, status, task):
        """Thread-safe role status update used by API and background worker."""
        if rid not in self.roles: raise ValueError(f"unknown agent role: {rid}")
        with self._state_lock:
            self._set_role(rid, status, task)

    def process(self, event: dict[str, Any]) -> dict[str, Any]:
        """Serialize state-changing events so concurrent HTTP requests cannot race the paper ledger."""
        with self._state_lock:
            return self._process_locked(event)

    def _process_locked(self, event: dict[str, Any]) -> dict[str, Any]:
        if any(not event.get(k) for k in ("event_id","event_type","occurred_at")): raise ValueError("event_id, event_type and occurred_at are required")
        eid=str(event["event_id"]); etype=str(event["event_type"]); source=str(event.get("source","lab-local")); payload=event.get("payload") or {}
        if not isinstance(payload,dict): raise ValueError("payload must be an object")
        if eid in self.event_ids:
            prior=next((e for e in self.events if e["event_id"]==eid), None)
            return {"event_id":eid,"status":"duplicate","original_status":prior["status"] if prior else "restored",
                    "result":prior["result"] if prior else {"note":"事件已存在於持久化事件帳本"}}
        result={"event_id":eid,"event_type":etype,"actions":[]}; status="processed"
        ledger_before = copy.deepcopy(self.ledger) if self.store.configured else None
        try:
            self._set_role("cio","working",f"分派事件：{etype}")
            if etype == "signal.created":
                self._set_role("quant","working","檢查訊號欄位與來源")
                if str(payload.get("mode","")).lower()!="paper": raise ValueError("signal rejected: payload.mode must explicitly be 'paper'")
                symbol=str(payload.get("symbol","")).strip().upper(); side=str(payload.get("side","")).upper(); qty=int(payload.get("quantity",0)); price=Decimal(str(payload.get("price","0")))
                if not symbol or side not in ("BUY","SELL") or qty<=0 or price<=0: raise ValueError("signal requires symbol, BUY/SELL, positive quantity and price")
                self._set_role("quant","success","訊號欄位檢查通過"); self._set_role("risk","working","檢查模擬資金與單筆風險")
                notional=price*qty
                snapshot = payload.get("market_snapshot")
                block_reason = market_data_block_reason(snapshot)
                if block_reason:
                    raise ValueError(f"risk rejected: {block_reason}")
                if notional>self.max_order_notional: raise ValueError(f"risk rejected: order notional {notional} exceeds limit {self.max_order_notional}")
                if side=="BUY" and not payload.get("allow_scale_in", False):
                    held = self.ledger.positions.get(symbol)
                    if held and held.quantity > 0:
                        raise ValueError("risk rejected: duplicate entry while position is already open")
                if side=="BUY" and notional*(Decimal("1")+self.fee_rate)>self.ledger.cash: raise ValueError("risk rejected: insufficient paper cash")
                if side=="SELL" and qty>self.ledger.positions.get(symbol,type("P",(),{"quantity":0})()).quantity: raise ValueError("risk rejected: sell quantity exceeds paper position")
                self._set_role("risk","success","風控檢查通過"); self._set_role("execution","working","建立模擬成交")
                fill=self.ledger.execute(symbol,side,qty,price)
                result["fill"]={"symbol":fill.symbol,"side":fill.side,"quantity":fill.quantity,"price":str(fill.price),"fee":str(fill.fee),"realized_pnl":str(fill.realized_pnl)}; result["actions"].append("paper_fill_created")
                self._set_role("execution","success","模擬成交完成")
            elif etype == "paper.exit_check":
                # Explicit, paper-only exit evaluator. It never calls a broker and
                # routes a triggered exit through the same ledger + durable event path.
                self._set_role("risk", "working", "檢查紙上持倉停損／停利")
                if str(payload.get("mode", "")).lower() != "paper":
                    raise ValueError("exit check rejected: payload.mode must explicitly be 'paper'")
                symbol = str(payload.get("symbol", "")).strip().upper()
                mark_price = Decimal(str(payload.get("mark_price", "0")))
                snapshot = payload.get("market_snapshot")
                if not symbol or mark_price <= 0:
                    raise ValueError("exit check requires symbol and positive mark_price")
                if not isinstance(snapshot, dict):
                    raise ValueError("risk rejected: MARKET_SNAPSHOT_REQUIRED_FOR_EXIT")
                block_reason = market_data_block_reason(snapshot)
                if block_reason:
                    raise ValueError(f"risk rejected: {block_reason}")
                position = self.ledger.positions.get(symbol)
                if not position or position.quantity <= 0:
                    result["actions"].append("no_open_position")
                else:
                    stop_loss_pct = Decimal(str(payload.get("stop_loss_pct", "0.02")))
                    take_profit_pct = Decimal(str(payload.get("take_profit_pct", "0.04")))
                    trigger = exit_trigger(position.average_price, mark_price,
                                           stop_loss_pct=stop_loss_pct,
                                           take_profit_pct=take_profit_pct)
                    if trigger is None:
                        result["actions"].append("exit_not_triggered")
                    else:
                        quantity = position.quantity
                        notional = mark_price * quantity
                        if notional > self.max_order_notional:
                            raise ValueError(f"risk rejected: exit notional {notional} exceeds limit {self.max_order_notional}")
                        self._set_role("execution", "working", f"執行紙上{trigger}：{symbol}")
                        fill = self.ledger.execute(symbol, "SELL", quantity, mark_price)
                        result["fill"] = {"symbol": fill.symbol, "side": fill.side,
                            "quantity": fill.quantity, "price": str(fill.price),
                            "fee": str(fill.fee), "realized_pnl": str(fill.realized_pnl)}
                        result["exit_reason"] = trigger
                        result["actions"].append("paper_exit_filled")
                        self._set_role("execution", "success", f"紙上{trigger}完成：{symbol}")
            elif etype=="prediction.recorded":
                self._set_role("quant","working","登記預測事件"); result["actions"].append("prediction_event_recorded"); self._set_role("quant","success","預測事件已登記")
            elif etype=="prediction.validated":
                self._set_role("auditor","working","處理預測驗證結果"); result["actions"].append("validation_event_recorded"); self._set_role("auditor","success","驗證結果已登記")
            elif etype=="agent.decision_recorded":
                agent_id = str(payload.get("agent_id") or "auditor")
                if agent_id not in ROLE_DEFS: raise ValueError("decision record has unknown agent_id")
                self._set_role(agent_id,"success",f"決策已留痕：{str(payload.get('decision_status') or 'RECORDED')}")
                result["actions"].append("traceable_agent_decision_persisted")
                result["decision_id"] = payload.get("decision_id")
            elif etype=="agent.research_evidence_recorded":
                agent_id = str(payload.get("agent_id") or "research")
                if agent_id not in ROLE_DEFS: raise ValueError("research evidence has unknown agent_id")
                self._set_role(agent_id,"success",f"研究證據已留存：{str(payload.get('tool') or payload.get('provider') or 'external source')[:80]}")
                result["actions"].append("external_research_evidence_persisted")
                result["evidence_id"] = payload.get("evidence_id")
            elif etype in ("telegram.sent","telegram.suppressed"): result["actions"].append("notification_event_recorded")
            elif etype=="session.closed": self._set_role("auditor","working","收盤事件已接收，準備產生報告"); result["actions"].append("daily_report_requested")
            else: result["actions"].append("event_recorded_no_handler")
        except Exception as exc:
            status="rejected" if "rejected:" in str(exc) or "risk rejected:" in str(exc) else "error"; result["error"]=str(exc); self._set_role("risk","warning",str(exc)[:100]); self._set_role("auditor","warning","事件未成功執行，已留下原因")
        finally:
            record={"event_id":eid,"event_type":etype,"occurred_at":str(event["occurred_at"]),"source":source,"status":status,"result":result,"processed_at":self._now(),"payload":payload}
            # Persist successful paper fill first, then event ledger. Roll back in-memory ledger if durable write fails.
            if self.store.configured:
                try:
                    if hasattr(self.store, "commit_event") and status == "processed" and result.get("fill"):
                        persisted_event = self.store.commit_event(event, {"status":status, **result}, result["fill"])
                    else:
                        if status == "processed" and result.get("fill"):
                            self.store.record_trade(event, result["fill"])
                        persisted_event = self.store.record_event(event, {"status":status, **result})
                    if persisted_event.get("event_seq") is not None:
                        result["event_seq"] = int(persisted_event["event_seq"])
                    result["persistence"] = "supabase"
                    if persisted_event.get("atomic"):
                        result["atomic_commit"] = True
                    record["result"] = result
                except Exception as exc:
                    if ledger_before is not None:
                        self.ledger = ledger_before
                    status = "persistence_error"
                    self.persistence_degraded = True
                    result = {"event_id":eid,"event_type":etype,"actions":[],"error":str(exc),"persistence":"failed"}
                    record["status"] = status; record["result"] = result
                    try: self.store.record_event(event, {"status":status, **result})
                    except Exception: pass
            else:
                result["persistence"] = "memory-only-dev"
                record["result"] = result
            self.events.insert(0,record); self.events=self.events[:500]
            if status != "persistence_error":
                self.event_ids.add(eid)
            if status=="processed": self._set_role("cio","success","事件處理完成"); self._set_role("auditor","idle","等待下一筆事件")
        if status=="processed" and etype=="session.closed":
            try: result["report"]=self.generate_report(str(event["occurred_at"])[:10]); result["actions"]=["daily_report_generated"]; record["result"]=result; self._set_role("auditor","success","收盤報告已產生")
            except Exception as exc: result["report_error"]=str(exc)
        return {"event_id":eid,"status":status,**result}

    def state(self, marks=None):
        marks = marks or {}
        with self._state_lock:
            snap=self.ledger.snapshot({k: Decimal(str(v)) for k,v in marks.items()})
            return {"mode":"isolated-paper-only","persistence":"supabase" if self.store.configured else "memory-only-dev","supabase_configured":self.store.configured,"restore_error":self.restore_error,"recovery":dict(self.recovery_summary),"persistence_degraded":self.persistence_degraded,"roles":[dict(x) for x in self.roles.values()],"events":copy.deepcopy(self.events[:30]),"ledger":snap,"counts":{"events":len(self.events),"fills":len(snap["fills"])}}

    def ingest_jsonl(self,path):
        outcomes=[]
        with open(path,encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    try: outcomes.append(self.process(json.loads(line)))
                    except Exception as exc: outcomes.append({"status":"invalid_event","error":str(exc)})
        return outcomes

    def build_report(self,date=None):
        date=date or self._now()[:10]
        events=[e for e in self.events if e["occurred_at"][:10]==date]
        fills=self.ledger.snapshot()["fills"]
        state=self.ledger.snapshot()
        return {"report_date":date,"generated_at":self._now(),"mode":"isolated-paper-only","persistence":"supabase" if self.store.configured else "memory-only-dev","event_count":len(events),"processed_count":sum(e["status"]=="processed" for e in events),"rejected_or_error_count":sum(e["status"] in ("rejected","error") for e in events),"fills_today":fills,"ledger":state,"safety":{"broker_connected":False,"live_orders_enabled":False,"production_modules_imported":False}}

    def generate_report(self,date=None):
        # Reports are persisted only in Supabase; no local report file is created.
        report = self.build_report(date)
        if self.store.configured:
            day = report['report_date']
            key = f"daily-{day}"
            self.store.record_report(key, day, report)
            report['persistence'] = 'supabase'
        return report
