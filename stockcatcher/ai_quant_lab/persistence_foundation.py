"""V17 durable session, checkpoint, idempotency and recovery primitives.

Supabase is the source of truth. This module never writes into Tianji 3K production.
"""
from __future__ import annotations
import hashlib, json, os, socket, uuid
from datetime import datetime, timezone, timedelta
from typing import Any

SCHEMA_VERSION = 1
APP_VERSION = "17.0.0"
AGENTS = {"cio", "quant", "research", "risk", "execution", "auditor"}


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def make_idempotency_key(namespace: str, *parts: Any) -> str:
    return f"{namespace}:{sha256_json(list(parts))}"


class PersistenceFoundation:
    def __init__(self, store, runtime_id: str | None = None, lease_seconds: int = 90):
        self.store = store
        self.runtime_id = runtime_id or f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"
        self.lease_seconds = max(15, int(lease_seconds))
        self.session_id: str | None = None
        self.parent_session_id: str | None = None
        self.recovery = {"status": "NOT_STARTED", "checkpoint_restored": False, "events_replayed": 0,
                         "interrupted_runs": 0, "stale_sessions_closed": 0, "warnings": []}

    def start(self) -> dict:
        if not self.store.configured:
            self.recovery.update(status="BLOCKED", warnings=["Supabase 未設定；不建立虛假的持久化 Session。"])
            return {"ok": False, "durable": False, **self.recovery}
        self.recovery["status"] = "RECOVERING"
        sessions = self.store.list_rows("ai_quant_lab_sessions", select="session_id,status,heartbeat_at,last_event_seq,started_at", order="started_at.desc", limit=100)
        if sessions:
            self.parent_session_id = sessions[0].get("session_id")
        now = datetime.now(timezone.utc)
        for row in sessions:
            if row.get("status") in ("STARTING", "RUNNING", "RECOVERING", "DEGRADED", "STOPPING"):
                sid = row.get("session_id")
                if not self.parent_session_id:
                    self.parent_session_id = sid
                try:
                    heartbeat = datetime.fromisoformat(str(row.get("heartbeat_at", "")).replace("Z", "+00:00"))
                    stale = now - heartbeat > timedelta(seconds=self.lease_seconds)
                except Exception:
                    stale = True
                if stale:
                    self.store.update_session(sid, {"status": "CRASHED", "closed_at": utcnow(), "updated_at": utcnow()})
                    self.recovery["stale_sessions_closed"] += 1
                else:
                    self.recovery["warnings"].append(f"偵測到仍有有效心跳的 Session：{sid}；為避免雙程序同時執行，啟動已阻止。")
                    self.recovery["status"] = "BLOCKED_DUPLICATE_RUNTIME"
                    return {"ok": False, "durable": True, "active_session_id": sid, **self.recovery}
        runs = self.store.list_rows("ai_quant_lab_agent_runs", select="run_id,status,lease_expires_at,updated_at", order="updated_at.asc", limit=1000)
        interrupted = 0
        for run in runs:
            if run.get("status") not in ("RUNNING", "WAITING_EXTERNAL"):
                continue
            try:
                expires = datetime.fromisoformat(str(run.get("lease_expires_at", "")).replace("Z", "+00:00"))
                expired = expires < now
            except Exception:
                expired = True
            if expired:
                self.store.update_agent_run(run["run_id"], {"status": "RETRY_PENDING", "updated_at": utcnow(),
                                                              "error_code": "LEASE_EXPIRED_ON_RECOVERY",
                                                              "error_message": "前次程序心跳／租約逾期，等待冪等重試。"})
                interrupted += 1
        self.recovery["interrupted_runs"] = interrupted
        self.session_id = str(uuid.uuid4())
        session = {"session_id": self.session_id, "parent_session_id": self.parent_session_id,
                   "runtime_id": self.runtime_id, "app_version": APP_VERSION, "status": "RUNNING",
                   "started_at": utcnow(), "heartbeat_at": utcnow(), "last_event_seq": 0,
                   "recovery_summary": dict(self.recovery), "metadata": {"paper_only": True, "production_write": False}}
        self.store.insert("ai_quant_lab_sessions", session)
        self.store.active_session_id = self.session_id
        self.recovery["status"] = "RECOVERED_WITH_WARNINGS" if self.recovery["warnings"] else "RECOVERED"
        self.store.update_session(self.session_id, {"status": "RUNNING", "recovery_summary": dict(self.recovery), "updated_at": utcnow()})
        return {"ok": True, "durable": True, "session_id": self.session_id, "parent_session_id": self.parent_session_id, **self.recovery}

    def heartbeat(self, last_event_seq: int | None = None) -> dict:
        if not self.session_id or not self.store.configured:
            return {"ok": False, "durable": False, "error": "No durable active session"}
        patch = {"heartbeat_at": utcnow(), "updated_at": utcnow(), "status": "RUNNING"}
        if last_event_seq is not None:
            patch["last_event_seq"] = int(last_event_seq)
        return self.store.update_session(self.session_id, patch)

    def close(self, status: str = "CLOSED") -> dict:
        if not self.session_id or not self.store.configured:
            return {"ok": False, "durable": False}
        if status not in ("CLOSED", "CRASHED", "DEGRADED"):
            raise ValueError("invalid session terminal status")
        return self.store.update_session(self.session_id, {"status": status, "closed_at": utcnow(), "heartbeat_at": utcnow(), "updated_at": utcnow()})

    def create_checkpoint(self, state: dict, last_event_seq: int = 0) -> dict:
        if not self.session_id or not self.store.configured:
            raise RuntimeError("checkpoint requires a durable active Supabase session")
        previous = self.store.list_rows("ai_quant_lab_checkpoints", select="checkpoint_seq", order="checkpoint_seq.desc", limit=1)
        seq = int(previous[0]["checkpoint_seq"]) + 1 if previous else 1
        checkpoint_id = str(uuid.uuid4())
        payload = {"schema_version": SCHEMA_VERSION, "state": state}
        row = {"checkpoint_id": checkpoint_id, "session_id": self.session_id, "checkpoint_seq": seq,
               "last_event_seq": int(last_event_seq), "state_json": payload, "state_sha256": sha256_json(payload),
               "schema_version": SCHEMA_VERSION, "is_valid": True, "created_at": utcnow()}
        self.store.insert("ai_quant_lab_checkpoints", row)
        self.store.update_session(self.session_id, {"last_checkpoint_id": checkpoint_id,
                                                     "last_event_seq": int(last_event_seq), "updated_at": utcnow()})
        return {"ok": True, "checkpoint_id": checkpoint_id, "checkpoint_seq": seq,
                "last_event_seq": int(last_event_seq), "state_sha256": row["state_sha256"]}

    def latest_valid_checkpoint(self) -> dict | None:
        if not self.store.configured:
            return None
        rows = self.store.list_rows("ai_quant_lab_checkpoints", select="*", order="checkpoint_seq.desc", limit=1000)
        for row in rows:
            payload = row.get("state_json") or {}
            if not row.get("is_valid", True):
                continue
            if int(row.get("schema_version", -1)) != SCHEMA_VERSION:
                continue
            if sha256_json(payload) != row.get("state_sha256"):
                continue
            return row
        return None

    def restore_into(self, engine) -> dict:
        """Restore checkpoint projections and replay post-checkpoint agent-state events.

        Paper cash/positions are rebuilt from the durable fill ledger by LabEngine first;
        events are replayed only as state projections to avoid executing fills twice.
        """
        checkpoint = self.latest_valid_checkpoint()
        last_seq = int(checkpoint.get("last_event_seq", 0)) if checkpoint else 0
        restored_roles = 0
        if checkpoint:
            payload = checkpoint.get("state_json") or {}
            snapshot = payload.get("state") or {}
            for saved in snapshot.get("roles", []):
                rid = saved.get("role_id")
                if rid in engine.roles:
                    engine.roles[rid].update({k: v for k, v in saved.items()
                                              if k in ("status", "task", "updated_at", "target_zone", "bubble")})
                    restored_roles += 1
            self.recovery["checkpoint_restored"] = True
        replayed = 0
        max_seq = last_seq
        offset = 0
        while True:
            rows = self.store.list_rows("ai_quant_lab_events", select="event_seq,event_type,payload,occurred_at", order="event_seq.asc",
                                         limit=1000, offset=offset, filters={"event_seq": f"gt.{last_seq}"})
            if not rows:
                break
            for row in rows:
                max_seq = max(max_seq, int(row.get("event_seq") or 0))
                envelope = row.get("payload") or {}
                event = envelope.get("event") or {}
                payload = event.get("payload") or {}
                if row.get("event_type") == "agent.state_changed":
                    rid = payload.get("agent_id")
                    if rid in engine.roles:
                        engine.roles[rid].update({k: payload[k] for k in ("status", "task", "target_zone", "bubble") if k in payload})
                        engine.roles[rid]["updated_at"] = event.get("occurred_at") or row.get("occurred_at")
                replayed += 1
            offset += len(rows)
            if len(rows) < 1000:
                break
        self.recovery["events_replayed"] = replayed
        self.recovery["last_event_seq"] = max_seq
        self.recovery["restored_agent_roles"] = restored_roles
        return {"checkpoint_id": checkpoint.get("checkpoint_id") if checkpoint else None,
                "checkpoint_restored": bool(checkpoint), "restored_agent_roles": restored_roles,
                "events_replayed": replayed, "last_event_seq": self.recovery["last_event_seq"]}

    def begin_agent_run(self, agent_id: str, task_type: str, *, idempotency_key: str,
                        prediction_id: str | None = None, input_event_ids: list[str] | None = None,
                        lease_owner: str | None = None) -> dict:
        if agent_id not in AGENTS:
            raise ValueError("unknown agent_id")
        if not self.store.configured:
            raise RuntimeError("Agent run requires Supabase persistence")
        row = {"run_id": str(uuid.uuid4()), "session_id": self.session_id, "agent_id": agent_id,
               "prediction_id": prediction_id, "task_type": task_type, "status": "RUNNING",
               "input_event_ids": input_event_ids or [], "result_json": {}, "attempt_count": 1,
               "lease_owner": lease_owner or self.runtime_id,
               "lease_expires_at": (datetime.now(timezone.utc) + timedelta(seconds=self.lease_seconds)).isoformat(),
               "started_at": utcnow(), "updated_at": utcnow(), "idempotency_key": idempotency_key,
               "schema_version": SCHEMA_VERSION}
        return self.store.upsert_agent_run(row)

    def finish_agent_run(self, run_id: str, status: str, result: dict | None = None, error: str | None = None) -> dict:
        if status not in ("COMPLETED", "FAILED", "RETRY_PENDING", "WAITING_EXTERNAL", "CANCELLED"):
            raise ValueError("invalid Agent run terminal status")
        patch = {"status": status, "result_json": result or {}, "updated_at": utcnow(),
                 "lease_expires_at": None, "completed_at": utcnow() if status in ("COMPLETED", "FAILED", "CANCELLED") else None,
                 "error_message": error}
        if error:
            patch["error_code"] = "AGENT_RUN_ERROR"
        return self.store.update_agent_run(run_id, patch)
