from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, time as dtime, timezone, timedelta
from pathlib import Path

import requests

from .data.config import (
    BREAKOUT_BUFFER_PCT,
    FUGLE_API_KEY,
    FUGLE_PENDING_TTL_SECONDS,
    MIS_INTERVAL_SECONDS,
    MIS_MAX_QUOTE_AGE_SECONDS,
    VOLUME_THRESHOLD_LOTS,
)
from .data.stock_universe import StockUniverseProvider
from .data.mis import MISProvider
from .core.snapshot import build_snapshot
from .core.state_machine import IntradayStateMachine
from .core.volume_predictor import IntradayVolumePredictor
from .core.mis_live_volume import MISLiveVolumeEstimator
from .core.prediction_score import IntradayPredictionScorer
from .core.simulator import IntradaySimulator
from .data.snapshot_filter import SnapshotUniverseFilter
from .data.fugle import FugleAPIError, FugleProvider
from .core.dynamic_candidate import evaluate_dynamic_history
from .core.dynamic_discovery import DynamicDiscoveryConfig, discovery_candidates
from .data.daily_refresh import DailyDataRefreshManager
from .data.finmind_budget import FinMindRequestBudget
from .data.finmind_initialization import ProductionCacheInitializer
from .notification.gate import evaluate_intraday_notification
from .notification.telegram import TelegramNotifier
from .validation.prediction_ledger import PredictionLedger
from .validation.prediction_chain import PredictionChain
from .validation.recovery_ledger import RecoveryLedger
from .core.recovery import RecoveryManager
from .core.process_lock import SingleInstanceLock
from .core.trading_session import TradingSession
from .validation.daily_report import build_daily_report, write_daily_report
from .validation.calibration_engine import PredictionCalibrationEngine

TAIPEI = timezone(timedelta(hours=8))


class TianjiProductionRunner:
    """Production coordinator for the daily 3K round.

    T-1 complete daily bars -> Stage 0~3 -> T-day watchlist -> MIS Radar
    -> intraday prediction -> notification -> close validation.
    """

    def __init__(self, repo_root: Path | None = None, telegram: bool = True):
        self.repo_root = (repo_root or Path(__file__).resolve().parents[1]).resolve()
        self.tianji = self.repo_root / "tianji_3k"
        self.cache = self.tianji / "cache"
        self.daily_cache = self.cache / "daily"
        self.pred_root = self.tianji / "predictions"
        self.ledger = PredictionLedger(self.pred_root)
        self.prediction_chain = PredictionChain(self.ledger)
        self.recovery_ledger = RecoveryLedger(self.tianji / "validation" / "recovery_events")
        self.recovery = RecoveryManager(self.pred_root / "runtime_checkpoint.json")
        self.notifier = TelegramNotifier() if telegram else TelegramNotifier("", "")
        self.states: dict[str, IntradayStateMachine] = {}
        self.contexts: dict[str, dict] = {}
        self.pool: list[dict] = []
        self.events: list[dict] = []
        self.notification_events: list[dict] = []
        self.ground_truth: list[dict] = []
        self.validation_rows: list[dict] = []
        self.volume_predictor = IntradayVolumePredictor()
        # In-memory only: EARLY-MIS volume estimation must never call a history API.
        self.mis_live_volume = MISLiveVolumeEstimator()
        self.prediction_scorer = IntradayPredictionScorer()
        self.mis_provider = None
        self.session = TradingSession()
        self.process_lock = SingleInstanceLock(self.pred_root / ".production.lock")
        self._last_notification_retry_at = 0.0
        self._gt_cutoff_recorded = False
        self.trade_date: str | None = None
        self._premarket_notified = False
        self.runtime_state_path: Path | None = None
        self.finmind_budget = FinMindRequestBudget(limit=580)
        self.data_refresh = DailyDataRefreshManager(
            self.daily_cache,
            self.cache / "data_freshness.json",
            budget=self.finmind_budget,
        )
        self.latest_completed_date: str | None = None
        # Intraday dynamic layer: market-wide MIS discovery, then selective
        # history enrichment. Existing premarket pool remains untouched.
        self.fugle_provider = FugleProvider(FUGLE_API_KEY)
        self.dynamic_contexts: dict[str, dict] = {}
        self.dynamic_attempts: dict[str, int] = {}
        # Transient history API failures are retried with bounded backoff rather
        # than consuming all three attempts in consecutive Radar cycles.
        self.dynamic_retry_after: dict[str, str] = {}
        self.universe_cache: dict[str, dict] = {}
        self.dynamic_discovery_config = DynamicDiscoveryConfig()
        self._next_radar_deadline = 0.0
        # Polling observability: distinguish scheduled cadence from the time
        # spent fetching MIS and processing a complete Radar cycle.
        self._last_radar_cycle_start_monotonic: float | None = None
        self._last_radar_cycle_duration_seconds: float | None = None
        self._fugle_health_checked = False
        self._fugle_health_future: Future | None = None
        self._fugle_health_status = "NOT_CHECKED"
        self._fugle_pending: dict[str, str] = {}
        self._expired_trigger_logged: set[str] = set()
        # Fugle runs off the Radar thread so a slow stock cannot block updates
        # for the rest of the market. Futures are consumed only by poll_once.
        self._fugle_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="tianji-fugle")
        self._fugle_futures: dict[str, Future] = {}
        self._fugle_last_attempt: dict[str, float] = {}
        self._latest_snapshots: dict[str, object] = {}
        self._latest_snapshot_received_at: dict[str, float] = {}
        self._fugle_retry_seconds = 30.0

    @staticmethod
    def _today() -> str:
        return datetime.now(TAIPEI).date().isoformat()

    @staticmethod
    def _iso_timestamp(value) -> str:
        """Normalize datetime/string timestamps used by the durable Radar state."""
        if hasattr(value, "isoformat"):
            return value.isoformat()
        return str(value)

    @staticmethod
    def _as_datetime(value) -> datetime:
        """Normalize persisted/live ISO timestamps to an aware datetime."""
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=TAIPEI)
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=TAIPEI)

    def _run_module(self, module, args):
        cmd = [sys.executable, "-m", module, *args]
        return subprocess.run(cmd, cwd=str(self.repo_root), check=True)

    def _set_runtime_path(self):
        if self.trade_date:
            p = self.pred_root / str(self.trade_date) / "runtime_state.json"
            p.parent.mkdir(parents=True, exist_ok=True)
            self.runtime_state_path = p

    def _save_runtime_state(self):
        if not self.runtime_state_path:
            return
        payload = {
            "schema_version": "runtime-v2.1",
            "trade_date": self.trade_date,
            "premarket_notified": self._premarket_notified,
            "dynamic_attempts": self.dynamic_attempts,
            "dynamic_retry_after": self.dynamic_retry_after,
            "states": {sid: sm.to_dict() for sid, sm in self.states.items()},
            "fugle_pending": self._fugle_pending,
            "fugle_health_status": self._fugle_health_status,
            "updated_at": datetime.now(TAIPEI).isoformat(),
        }
        tmp = self.runtime_state_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.runtime_state_path)
        self.recovery.heartbeat("STATE_SAVED", success=True)

    def _load_runtime_state(self):
        self._set_runtime_path()
        if not self.runtime_state_path or not self.runtime_state_path.exists():
            return
        try:
            data = json.loads(self.runtime_state_path.read_text(encoding="utf-8"))
            self._premarket_notified = bool(data.get("premarket_notified", False))
            self.dynamic_attempts = {str(k): int(v) for k, v in (data.get("dynamic_attempts", {}) or {}).items()}
            self.dynamic_retry_after = {str(k): str(v) for k, v in (data.get("dynamic_retry_after", {}) or {}).items()}
            self._fugle_pending = {str(k): str(v) for k, v in (data.get("fugle_pending", {}) or {}).items()}
            self._fugle_health_status = str(data.get("fugle_health_status", "NOT_CHECKED"))
            for sid, state in data.get("states", {}).items():
                self.states[str(sid)] = IntradayStateMachine.from_dict(state)
        except (OSError, ValueError, TypeError):
            return

    def _load_today_predictions(self):
        if not self.trade_date:
            return []
        return list(self.ledger.iter_predictions(self.trade_date))

    def build_premarket_pool(self, trade_date: str | None = None):
        """Build a NEW trading-day watchlist from the latest completed daily data."""
        self.trade_date = trade_date or self._today()
        self.recovery.start(self.trade_date, "BUILD_PREMARKET_POOL")
        self.recovery_ledger.append(self.trade_date, {"event_type":"RUN_START", "phase":"BUILD_PREMARKET_POOL", "at":datetime.now(TAIPEI).isoformat()})
        self._set_runtime_path()
        self.cache.mkdir(parents=True, exist_ok=True)
        (self.cache / "reference").mkdir(parents=True, exist_ok=True)


        s0j = self.cache / "stage0_production.json"
        s0c = self.cache / "stage0_production.csv"
        s1j = self.cache / "stage1_trend.json"
        s1c = self.cache / "stage1_trend.csv"
        stage2j = self.cache / "stage2_breakout.json"
        stage3j = self.cache / "stage3_volume.json"
        finalj = self.cache / "final_3k_pool.json"
        pool_dir = self.cache / "pools"
        pool_dir.mkdir(parents=True, exist_ok=True)
        daily_pool = pool_dir / f"{self.trade_date}.json"

        # Freshness MUST be checked before reusing an existing daily pool.
        # Otherwise a pool generated earlier from stale K data could survive
        # a restart and silently remain the day's watchlist.
        freshness = self.data_refresh.refresh(self.trade_date)
        self.latest_completed_date = freshness.latest_completed_date
        official = self.data_refresh.refresh_official_daily(self.latest_completed_date)
        print("=" * 72)
        print("天機 3K DATA CONTEXT")
        print("=" * 72)
        print(f"Trade Date             : {self.trade_date}")
        print(f"Latest Completed K     : {freshness.latest_completed_date}")
        print(f"Cache Latest K         : {freshness.cache_latest_after}")
        print("Data Source            : OFFICIAL TWSE/TPEx + CACHE + FINMIND(HISTORY ONLY)")
        print(f"Official Daily         : {official['status']} TWSE={official.get('twse_rows',0):,} TPEx={official.get('tpex_rows',0):,} symbols={official.get('rows_written',0):,}")
        print(f"Data Freshness         : {freshness.status}")
        b = self.finmind_budget.snapshot()
        print(f"FinMind Budget         : {b['used']}/{b['limit']} used (rolling 60m), remaining={b['remaining']}")
        print("=" * 72)
        if official["status"] != "READY":
            raise RuntimeError("OFFICIAL_DAILY_SNAPSHOT_NOT_READY")

        if daily_pool.exists():
            existing_pool = json.loads(daily_pool.read_text(encoding="utf-8"))
            existing_dates = {str(x.get("date") or x.get("latest_date") or "") for x in existing_pool if isinstance(x, dict)}
            if existing_pool and existing_dates and existing_dates == {self.latest_completed_date}:
                self.pool = existing_pool
                self._load_pool_from_memory()
                self._load_runtime_state()
                if self.pool and self.notifier.enabled and not self._premarket_notified:
                    result = self.notifier.send_premarket_watchlist(self.trade_date, self.pool)
                    self._record_notification(
                        event_type="PREMARKET_WATCHLIST_NOTIFICATION",
                        status=result.get("status", "FAILED"),
                        message_id=result.get("message_id"),
                    )
                    self._premarket_notified = result.get("status") == "SENT"
                    self._save_runtime_state()
                return self.pool
            # Stale daily pool: do not reuse it. Rebuild from refreshed cache.
            daily_pool.unlink(missing_ok=True)

        from .tools.stage0_production import main as stage0_main
        stage0_main([
            "--repo-root", str(self.repo_root),
            "--cache-dir", str(self.daily_cache),
            "--volume-threshold", str(VOLUME_THRESHOLD_LOTS),
            "--reference-cache", str(self.cache / "reference" / "stage0_reference.json"),
            "--csv", str(s0c), "--json", str(s0j),
        ])
        stage0_payload = json.loads(s0j.read_text(encoding="utf-8"))
        stage0_symbols = [str(x.get("symbol")) for x in stage0_payload if x.get("final_stage0_pass")]
        initializer = ProductionCacheInitializer(
            cache_dir=self.daily_cache,
            checkpoint_path=self.cache / "production_cache_initialization_stage0.json",
            budget=self.finmind_budget,
            calendar=self.data_refresh.calendar,
            provider=self.data_refresh.provider,
            universe_provider=StockUniverseProvider(),
            min_universe_symbols=0,
        )
        init_result = initializer.initialize(
            self.trade_date,
            bars_required=61,
            resume=True,
            wait_for_budget=False,
            symbols=stage0_symbols,
        )
        print(f"History Initialization : status={init_result.status} requested={init_result.total_symbols:,} completed={init_result.completed_symbols:,} pending={init_result.pending_symbols:,} FinMind={init_result.requests_used}/580")
        if init_result.status not in {"COMPLETE", "COMPLETE_WITH_SKIPS"}:
            self.recovery_ledger.append(self.trade_date, {
                "event_type": "HISTORY_INITIALIZATION_NOT_COMPLETE",
                "status": init_result.status,
                "pending": init_result.pending_symbols,
                "message": init_result.message,
                "at": datetime.now(TAIPEI).isoformat(),
            })
            raise RuntimeError(f"HISTORY_INITIALIZATION_{init_result.status}")
        if init_result.status == "COMPLETE_WITH_SKIPS":
            checkpoint = initializer.load_checkpoint() or {}
            skipped = [str(x) for x in checkpoint.get("skipped_symbols", [])]
            self.recovery_ledger.append(self.trade_date, {
                "event_type": "HISTORY_SYMBOLS_SKIPPED_AFTER_3_FAILURES",
                "count": len(skipped),
                "symbols": skipped[:200],
                "message": init_result.message,
                "at": datetime.now(TAIPEI).isoformat(),
            })
            print(f"History Initialization : CONTINUE_WITH_SKIPS skipped={len(skipped):,}")
        from .stage1.trend_engine import main as stage1_main
        # Only history-ready Stage 0 candidates may enter Stage 1. Symbols
        # quarantined after three history/FinMind failures are explicitly
        # removed from the downstream pipeline for this run.
        init_checkpoint = initializer.load_checkpoint() or {}
        skipped_symbols = {str(x) for x in init_checkpoint.get("skipped_symbols", [])}
        if skipped_symbols:
            stage0_rows = json.loads(s0j.read_text(encoding="utf-8"))
            if isinstance(stage0_rows, dict):
                stage0_rows = stage0_rows.get("rows", stage0_rows.get("data", []))
            stage0_ready_rows = [
                row for row in stage0_rows
                if isinstance(row, dict)
                and str(row.get("symbol", row.get("stock_id", ""))) not in skipped_symbols
            ]
            stage0_ready_path = self.cache / "stage0_history_ready.json"
            stage0_ready_path.write_text(
                json.dumps(stage0_ready_rows, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        else:
            stage0_ready_path = s0j

        stage1_main([
            "--stage0-json", str(stage0_ready_path), "--cache-dir", str(self.daily_cache),
            "--csv", str(s1c), "--json", str(s1j),
        ])
        self._run_module("tianji_3k.stage2.breakout_engine", [
            "--stage1-json", str(s1j), "--cache-dir", str(self.daily_cache),
            "--csv", str(self.cache / "stage2_breakout.csv"), "--json", str(stage2j),
        ])
        self._run_module("tianji_3k.stage3.volume_engine", [
            "--stage2-json", str(stage2j), "--cache-dir", str(self.daily_cache),
            "--csv", str(self.cache / "stage3_volume.csv"), "--json", str(stage3j),
        ])
        self._run_module("tianji_3k.core.final_pool", [
            "--stage3-json", str(stage3j), "--stage2-json", str(stage2j),
            "--output", str(finalj),
        ])

        pool = json.loads(finalj.read_text(encoding="utf-8"))
        universe = {x["symbol"]: x for x in StockUniverseProvider().fetch()}
        s1 = {str(x["symbol"]): x for x in json.loads(s1j.read_text(encoding="utf-8"))}
        s0 = {str(x["symbol"]): x for x in json.loads(s0j.read_text(encoding="utf-8"))}

        self.pool = []
        self.contexts = {}
        self.states = {}
        self.events = []
        self.notification_events = []
        self.validation_rows = []
        self._premarket_notified = False
        self.runtime_state_path: Path | None = None

        for x in pool:
            sid = str(x["symbol"])
            u = universe.get(sid, {})
            t = s1.get(sid, {})
            a = s0.get(sid, {})
            item = {
                **x,
                "name": u.get("name") or t.get("name", ""),
                "market": u.get("market", ""),
                "industry": u.get("industry", ""),
                "stage0": a,
                "stage1": t,
            }
            self.pool.append(item)
            context = {
                "trade_date": self.trade_date,
                "symbol": sid,
                "name": item["name"],
                "market": item["market"],
                "industry": item.get("industry", ""),
                "source_data_date": x.get("date") or x.get("latest_date") or self.latest_completed_date,
                "previous_close": float(x.get("close") or 0),
                "k1_high": float(x.get("k1_high") or 0),
                "k2_high": float(x.get("k2_high") or 0),
                "breakout_level": float(x.get("breakout_level") or 0),
                "ma20": float(t.get("ma20") or 0),
                "ma60": float(t.get("ma60") or 0),
                "ma20_prev": float(t.get("ma20_prev") or 0),
                "vma5_lots": float(x.get("stage3", {}).get("vma5_lots") or x.get("vma5_lots") or 0),
                "yesterday_volume_lots": float(x.get("stage3", {}).get("yesterday_volume_lots") or x.get("yesterday_volume_lots") or 0),
                "stage0_pass": True,
                "stage1_pass": True,
                "stage2_pass": True,
                "stage3_pass": True,
                "final_pool": True,
            }
            self.contexts[sid] = context
            self.states[sid] = IntradayStateMachine()
            self.ledger.write_context(context)

        daily_pool.write_text(json.dumps(self.pool, ensure_ascii=False, indent=2), encoding="utf-8")
        self._set_runtime_path()
        self._record_premarket_event()
        if self.pool and self.notifier.enabled and not self._premarket_notified:
            result = self.notifier.send_premarket_watchlist(self.trade_date, self.pool)
            self._record_notification(
                event_type="PREMARKET_WATCHLIST_NOTIFICATION",
                status=result.get("status", "FAILED"),
                message_id=result.get("message_id"),
            )
            self._premarket_notified = result.get("status") == "SENT"
        self._save_runtime_state()
        return self.pool

    def _record_premarket_event(self):
        event = {
            "event_type": "PREMARKET_WATCHLIST",
            "trade_date": self.trade_date,
            "symbols": [str(x.get("symbol")) for x in self.pool],
            "pool_count": len(self.pool),
            "source_data_dates": sorted({str(x.get("date") or x.get("latest_date") or self.latest_completed_date or "") for x in self.pool}),
            "created_at": datetime.now(TAIPEI).isoformat(),
        }
        self.events.append(event)
        self.ledger.append_daily_event(self.trade_date, event)

    def _record_notification(self, event_type: str, status: str, message_id=None, **extra):
        event = {
            "event_type": event_type,
            "trade_date": self.trade_date,
            "status": status,
            "telegram_message_id": message_id,
            "created_at": datetime.now(TAIPEI).isoformat(),
            **extra,
        }
        self.notification_events.append(event)
        self.ledger.append_daily_event(self.trade_date, event)

    def _radar_rows(self):
        if not self.universe_cache:
            self.universe_cache = {str(x["symbol"]): x for x in StockUniverseProvider().fetch()}
        out = []
        seen = set()
        for x in list(self.pool) + [dict(v, symbol=k) for k, v in self.dynamic_contexts.items()]:
            sid = str(x["symbol"])
            if sid in seen:
                continue
            seen.add(sid)
            u = self.universe_cache.get(sid, {})
            out.append({
                "symbol": sid,
                "name": u.get("name", x.get("name", "")),
                "market": u.get("market", x.get("market", "")),
                "product_type": "COMMON_STOCK",
                "security_type": "COMMON_STOCK",
                "status": "NORMAL",
                "yesterday_volume_lots": float(
                    x.get("stage3", {}).get("yesterday_volume_lots")
                    or x.get("yesterday_volume_lots")
                    or u.get("previous_volume_lots")
                    or 0
                ),
            })
        return out

    def _dynamic_candidate_gate(self, raw: dict, universe: dict[str, dict]) -> list[dict]:
        """Market-wide MIS discovery only; historical APIs are not touched."""
        candidates = discovery_candidates(
            raw,
            universe,
            existing=set(self.contexts) | set(self.dynamic_contexts),
            attempts=self.dynamic_attempts,
            config=self.dynamic_discovery_config,
        )
        now = datetime.now(TAIPEI)
        ready = []
        cooldown = 0
        for candidate in candidates:
            sid = str(candidate.get("symbol", ""))
            retry_at = self.dynamic_retry_after.get(sid)
            if retry_at:
                try:
                    if self._as_datetime(retry_at) > now:
                        cooldown += 1
                        continue
                except (TypeError, ValueError, OverflowError):
                    # Bad persisted cooldown must not permanently block a stock.
                    self.dynamic_retry_after.pop(sid, None)
            ready.append(candidate)
        self._last_dynamic_cooldown_skipped = cooldown
        return ready

    def _enrich_dynamic_candidates(self, candidates: list[dict]) -> int:
        """Spend FinMind only on candidates that already passed the MIS gate."""
        if not candidates or not self.latest_completed_date:
            return 0
        calendar = self.data_refresh.calendar
        dates = calendar.previous_trading_days(self.latest_completed_date, 61, include_end=True)
        if not dates:
            return 0
        start = dates[0].isoformat()
        added = 0
        # Small per-cycle guard prevents a sudden market-wide surge from
        # consuming the rolling FinMind budget in one Radar iteration.
        for c in candidates[: self.dynamic_discovery_config.max_history_enrich_per_cycle]:
            sid = str(c["symbol"])
            attempt = self.dynamic_attempts.get(sid, 0) + 1
            self.dynamic_attempts[sid] = attempt
            try:
                frame = self.data_refresh.provider.get_daily(sid, start, self.latest_completed_date)
                self.dynamic_retry_after.pop(sid, None)
                result = evaluate_dynamic_history(
                    sid, frame, name=c.get("name", ""), market=c.get("market", ""), trade_date=self.trade_date or self._today()
                )
                self.ledger.append_event(self.trade_date or self._today(), sid, {
                    "event_type": "DYNAMIC_CANDIDATE_HISTORY",
                    "reason": result.reason,
                    "observed_at": datetime.now(TAIPEI).isoformat(),
                    "mis_candidate": c,
                })
                if not result.eligible or not result.context:
                    continue
                ctx = result.context
                self.dynamic_contexts[sid] = ctx
                self.contexts[sid] = ctx
                self.states[sid] = IntradayStateMachine()
                self.ledger.write_context(ctx)
                added += 1
                print(f"🟢 DYNAMIC CANDIDATE | {sid} {c.get('name','')} | +{c.get('up_pct',0):.2f}% | Breakout={ctx['breakout_level']:.2f} | VMA5={ctx['vma5_lots']:.0f}張", flush=True)
            except Exception as exc:
                # Attempts remain capped at the existing max_history_attempts,
                # but transient errors are spaced out so a bad/empty response
                # cannot consume all retries in adjacent 20-second Radar cycles.
                backoff_seconds = min(60 * (2 ** max(0, attempt - 1)), 300)
                retry_at = datetime.now(TAIPEI) + timedelta(seconds=backoff_seconds)
                self.dynamic_retry_after[sid] = retry_at.isoformat()
                print(
                    f"⚠️ DYNAMIC HISTORY | {sid} | {type(exc).__name__}: {str(exc)[:180]} "
                    f"| attempt={attempt}/{self.dynamic_discovery_config.max_history_attempts} "
                    f"| retry_after_s={backoff_seconds}", flush=True,
                )
                self.ledger.append_event(self.trade_date or self._today(), sid, {
                    "event_type": "DYNAMIC_CANDIDATE_HISTORY_ERROR",
                    "error_type": type(exc).__name__,
                    "message": str(exc)[:300],
                    "attempt": attempt,
                    "retry_after": retry_at.isoformat(),
                    "observed_at": datetime.now(TAIPEI).isoformat(),
                })
        return added

    def _save_dynamic_candidates(self):
        if not self.trade_date:
            return
        path = self.cache / "pools" / f"{self.trade_date}_dynamic.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(list(self.dynamic_contexts.values()), ensure_ascii=False, indent=2), encoding="utf-8")

    def _load_dynamic_candidates(self):
        if not self.trade_date:
            return
        path = self.cache / "pools" / f"{self.trade_date}_dynamic.json"
        if not path.exists():
            return
        try:
            rows = json.loads(path.read_text(encoding="utf-8"))
            for ctx in rows if isinstance(rows, list) else []:
                sid = str(ctx.get("symbol", ""))
                if not sid:
                    continue
                self.dynamic_contexts[sid] = ctx
                self.contexts[sid] = ctx
                self.states.setdefault(sid, IntradayStateMachine())
        except (OSError, ValueError, TypeError):
            return

    def _print_radar_monitor(self, raw: dict, rows: list[dict]):
        """Print the exact stocks currently attached to the intraday Radar."""
        now = datetime.now(TAIPEI).strftime("%H:%M:%S")
        print("\n" + "=" * 96, flush=True)
        print(f"🔎 TIANJI 3K RADAR | {now} | 監控中 {len(rows)} 檔 | MIS 回傳 {len(raw)} 檔", flush=True)
        print("=" * 96, flush=True)
        print(f"{'股號':<8}{'股名':<16}{'來源':<10}{'市場':<8}{'現價':>12}{'State':<22}", flush=True)
        print("-" * 96, flush=True)
        dynamic_ids = set(self.dynamic_contexts)
        for row in rows:
            sid = str(row.get("symbol", ""))
            name = str(row.get("name", ""))[:12]
            source = "DYNAMIC" if sid in dynamic_ids else "PREMARKET"
            market = str(row.get("market", ""))[:6]
            item = raw.get(sid, {})
            price = item.get("current_price")
            price_text = f"{float(price):,.2f}" if price not in (None, "") else "--"
            quote_age = item.get("quote_age_seconds")
            quote_time_known = item.get("quote_time_known")
            if quote_time_known is False or (
                quote_age is not None and float(quote_age) > MIS_MAX_QUOTE_AGE_SECONDS
            ):
                price_text = f"{price_text}!"
            state_obj = self.states.get(sid)
            state = getattr(getattr(state_obj, "state", None), "value", "NOT_LOADED")
            print(f"{sid:<8}{name:<16}{source:<10}{market:<8}{price_text:>12}{state:<22}", flush=True)
        print("-" * 96, flush=True)
        print(f"📌 PREMARKET={len(self.pool)} | DYNAMIC={len(self.dynamic_contexts)} | TOTAL={len(rows)}", flush=True)
        print("ℹ️ 價格欄位帶 ! 代表 MIS 最後成交時間超過允許新鮮度或時間未知", flush=True)
        print(f"✅ RADAR ACTIVE | 下一次監控約 {MIS_INTERVAL_SECONDS} 秒", flush=True)
        print("=" * 96, flush=True)

    def _timed_fugle_evaluate(self, symbol: str):
        started = time.monotonic()
        print(f"🔵 FUGLE 5M REQUEST | {symbol} | timeframe=5 | mode=ASYNC", flush=True)
        try:
            result = self.fugle_provider.evaluate_3k_micro_breakout(symbol, min_volume_ratio=1.05)
            return result
        finally:
            elapsed_ms = (time.monotonic() - started) * 1000
            print(f"⏱️ FUGLE REQUEST TIMING | {symbol} | elapsed_ms={elapsed_ms:.1f}", flush=True)

    def _pending_trigger_age_seconds(self, sid: str) -> float:
        started_at = getattr(self, "_fugle_pending", {}).get(str(sid))
        if not started_at:
            return 0.0
        try:
            return max(0.0, (datetime.now(TAIPEI) - self._as_datetime(started_at)).total_seconds())
        except (TypeError, ValueError, OverflowError):
            # A malformed persisted timestamp must not permit an indefinitely
            # retrying trigger to produce a late alert.
            return float(FUGLE_PENDING_TTL_SECONDS + 1)

    @staticmethod
    def _mis_quote_freshness(snap):
        """Validate exchange last-trade time independently of HTTP receive time."""
        known = getattr(snap, "quote_time_known", None)
        age = getattr(snap, "quote_age_seconds", None)
        if known is False:
            return False, "QUOTE_TIME_UNKNOWN", age
        if age is not None and float(age) > MIS_MAX_QUOTE_AGE_SECONDS:
            return False, "QUOTE_TOO_OLD", float(age)
        # None is retained for older unit/replay snapshots that have no quote
        # metadata; the live MIS provider always supplies quote_time_known.
        return True, "FRESH", float(age) if age is not None else None

    def _finalize_mis_early(self, sid: str, ctx: dict, snap, previous_snap=None):
        """Send EARLY from MIS price + lightweight live-volume pace evidence.

        The estimator uses only current MIS cumulative-volume snapshots and the
        already-loaded daily VMA5. It never requests Fugle/history data. The
        first valid alert waits for a 45-90s observation window to avoid treating
        a single small volume tick as meaningful acceleration.
        """
        sm = self.states.setdefault(sid, IntradayStateMachine())
        trigger_age = self._pending_trigger_age_seconds(sid)
        if trigger_age > FUGLE_PENDING_TTL_SECONDS:
            if sid not in self._expired_trigger_logged:
                print(
                    f"🟠 EARLY MIS EXPIRED | {sid} | trigger_age_s={trigger_age:.1f} "
                    f"| ttl_s={FUGLE_PENDING_TTL_SECONDS} | suppress late alert",
                    flush=True,
                )
                self._expired_trigger_logged.add(sid)
            return
        quote_fresh, quote_reason, quote_age = self._mis_quote_freshness(snap)
        if not quote_fresh:
            print(
                f"🟠 EARLY MIS SUPPRESSED | {sid} | reason={quote_reason} "
                f"| quote_age_s={quote_age} | no stale-price alert",
                flush=True,
            )
            return
        received_age = time.monotonic() - self._latest_snapshot_received_at.get(sid, 0.0)
        if received_age > 45.0:
            return

        effective = snap.current_price >= float(ctx["breakout_level"]) * (1 + BREAKOUT_BUFFER_PCT / 100)
        live_valid = (
            snap.is_traded and snap.current_price > snap.today_open
            and snap.up_pct >= 4.0 and effective
            and snap.previous_close > 0 and snap.today_open > 0
        )
        if not live_valid:
            print(f"🟡 EARLY MIS WAIT | {sid} | live_valid=False", flush=True)
            return

        estimator = getattr(self, "mis_live_volume", None)
        if estimator is None:
            estimator = MISLiveVolumeEstimator()
            self.mis_live_volume = estimator
        volume_evidence = estimator.observe(
            sid, snap.observed_at, snap.cumulative_volume_lots, float(ctx.get("vma5_lots") or 0.0)
        )
        if not volume_evidence["pass"]:
            print(
                f"🟡 EARLY MIS VOLUME WAIT | {sid} | ready={volume_evidence['ready']} "
                f"| reason={volume_evidence['reason']} | window_s={volume_evidence['window_seconds']:.1f} "
                f"| last_gap_s={volume_evidence.get('last_snapshot_gap_seconds')} "
                f"| samples={volume_evidence.get('sample_count')} "
                f"| reset_reason={volume_evidence.get('history_reset_reason')} "
                f"| max_window_s={volume_evidence.get('max_window_seconds')} "
                f"| delta_lots={volume_evidence['volume_delta_lots']:.1f} "
                f"| live_ratio={volume_evidence['live_volume_ratio']} "
                f"| baseline={volume_evidence['baseline_source']}", flush=True,
            )
            return

        prior_predictions = list(self.ledger.iter_predictions(ctx["trade_date"]))
        already_created = any(
            e.get("symbol") == sid
            and str(e.get("trigger_snapshot", {}).get("signal_level", "")).upper() == "EARLY"
            and str(e.get("trigger_snapshot", {}).get("early_evidence_source", "")) == "MIS_LIVE"
            for e in prior_predictions
        )
        if already_created:
            return

        projection = self.volume_predictor.project(
            snap.cumulative_volume_lots, self._as_datetime(snap.observed_at), ctx["vma5_lots"]
        )
        projected_ratio = projection.projected_ratio
        trigger = {
            **snap.to_dict(), "k1_high": ctx["k1_high"], "k2_high": ctx["k2_high"],
            "breakout_level": ctx["breakout_level"], "effective_breakout": effective,
            "volume_prediction_pass": True, "fugle_5m_confirmation": {},
            "early_evidence_source": "MIS_LIVE", "signal_level": "EARLY",
            "confirmed_snapshots": 2,
            "mis_volume_delta_lots": volume_evidence["volume_delta_lots"],
            "mis_live_volume_ratio": volume_evidence["live_volume_ratio"],
            "mis_volume_window_seconds": volume_evidence["window_seconds"],
            "mis_volume_expected_lots": volume_evidence["expected_volume_lots"],
            "mis_volume_baseline_source": volume_evidence["baseline_source"],
            "mis_volume_required_ratio": volume_evidence["required_ratio"],
            "state": sm.state.value,
        }
        vol = {
            "cumulative_volume_lots": snap.cumulative_volume_lots,
            "volume_delta_lots": volume_evidence["volume_delta_lots"],
            "live_volume_ratio": volume_evidence["live_volume_ratio"],
            "live_volume_window_seconds": volume_evidence["window_seconds"],
            "live_volume_expected_lots": volume_evidence["expected_volume_lots"],
            "live_volume_baseline_5m_lots": volume_evidence["baseline_5m_lots"],
            "live_volume_baseline_source": volume_evidence["baseline_source"],
            "live_volume_required_ratio": volume_evidence["required_ratio"],
            "elapsed_minutes": projection.elapsed_minutes,
            "projected_volume_lots": projection.projected_volume_lots,
            "projected_ratio": projected_ratio, "baseline_start": projection.baseline_start,
            "baseline_end": projection.baseline_end, "vma5_lots": ctx["vma5_lots"],
            "projection_ready": projection.ready, "signal_level": "EARLY",
            "early_evidence_source": "MIS_LIVE",
        }
        score = self.prediction_scorer.score(
            context=ctx, current_price=snap.current_price, up_pct=snap.up_pct,
            projected_ratio=projected_ratio, effective_breakout=effective, confirmed_snapshots=2,
        )
        trigger["prediction_score"] = score.total
        trigger["prediction_score_breakdown"] = score.to_dict()
        vol["prediction_score_volume_component"] = score.volume
        gate = evaluate_intraday_notification(snap.up_pct).to_dict()
        event = self.ledger.create_prediction(ctx, trigger, vol, gate)
        self.events.append(event)
        print(
            f"🟡 INTRADAY_3K_PREDICTION | {sid} | level=EARLY | evidence=MIS_LIVE "
            f"| price={snap.current_price:.2f} | breakout={ctx['breakout_level']:.2f} "
            f"| volume_delta_lots={volume_evidence['volume_delta_lots']:.1f} "
            f"| live_volume_ratio={volume_evidence['live_volume_ratio']:.2f}x "
            f"| window_s={volume_evidence['window_seconds']:.1f} | projected_ratio={projected_ratio} "
            f"| trigger_age_s={trigger_age:.1f} | snapshot_received_age_s={received_age:.2f}",
            flush=True,
        )
        if gate["should_send"] and self.notifier.enabled:
            telegram_started = time.monotonic()
            telegram_started_at = datetime.now(TAIPEI).isoformat()
            result = self.notifier.send_intraday_prediction(event)
            telegram_elapsed_ms = (time.monotonic() - telegram_started) * 1000
            status = result.get("status", "FAILED")
            print(
                f"📨 TELEGRAM SEND TIMING | {sid} | evidence=MIS_LIVE | status={status} "
                f"| elapsed_ms={telegram_elapsed_ms:.1f} | started_at={telegram_started_at}",
                flush=True,
            )
            self._record_notification(
                event_type="INTRADAY_3K_PREDICTION_NOTIFICATION", status=status,
                message_id=result.get("message_id"), prediction_id=event["prediction_id"],
                symbol=sid, up_pct=snap.up_pct,
            )
            self.ledger.append_event(ctx["trade_date"], sid, {
                "event_type": "NOTIFICATION", "prediction_id": event["prediction_id"],
                "notification_status": status, "telegram_message_id": result.get("message_id"),
                "sent_at": datetime.now(TAIPEI).isoformat(), "snapshot_id": snap.snapshot_id,
                "current_price": snap.current_price, "signal_level": "EARLY",
                "early_evidence_source": "MIS_LIVE",
                "mis_live_volume_ratio": volume_evidence["live_volume_ratio"],
            })
        else:
            status = "SUPPRESSED" if not gate["should_send"] else "DISABLED"
            self._record_notification(
                event_type="INTRADAY_3K_PREDICTION_NOTIFICATION", status=status,
                prediction_id=event["prediction_id"], symbol=sid, up_pct=snap.up_pct,
            )
        self._save_runtime_state()

    def _finalize_fugle_result(self, sid: str, ctx: dict, snap, micro):
        """Finalize a completed 5M result against the newest MIS quote."""
        sm = self.states.setdefault(sid, IntradayStateMachine())
        trigger_age = self._pending_trigger_age_seconds(sid)
        if trigger_age > FUGLE_PENDING_TTL_SECONDS:
            if sid not in self._expired_trigger_logged:
                print(
                    f"🟠 FUGLE RESULT EXPIRED | {sid} | trigger_age_s={trigger_age:.1f} "
                    f"| ttl_s={FUGLE_PENDING_TTL_SECONDS} | no late notification",
                    flush=True,
                )
                self._expired_trigger_logged.add(sid)
            return
        quote_fresh, quote_reason, quote_age = self._mis_quote_freshness(snap)
        if not quote_fresh:
            print(
                f"🟠 SIGNAL SUPPRESSED STALE MIS | {sid} | reason={quote_reason} "
                f"| quote_age_s={quote_age} | no late notification",
                flush=True,
            )
            self.ledger.append_event(ctx["trade_date"], sid, {
                "event_type": "SIGNAL_SUPPRESSED_STALE_MIS_QUOTE",
                "observed_at": datetime.now(TAIPEI).isoformat(),
                "quote_time": getattr(snap, "quote_time", None),
                "quote_age_seconds": quote_age,
                "reason": quote_reason,
            })
            return
        snapshot_age = time.monotonic() - self._latest_snapshot_received_at.get(sid, 0.0)
        if snapshot_age > 45.0:
            print(f"🟡 SIGNAL WAITING FOR FRESH MIS | {sid} | snapshot_age_s={snapshot_age:.1f} | no stale-price notification", flush=True)
            self.ledger.append_event(ctx["trade_date"], sid, {
                "event_type": "SIGNAL_WAITING_FOR_FRESH_MIS",
                "observed_at": datetime.now(TAIPEI).isoformat(),
                "snapshot_age_seconds": round(snapshot_age, 2),
            })
            return
        if not micro:
            print(f"🟡 FUGLE 5M REJECT | {sid} | micro confirmation not met | ACTION=RETRY", flush=True)
            self.ledger.append_event(ctx["trade_date"], sid, {
                "event_type": "FUGLE_5M_CONFIRMATION_REJECTED",
                "observed_at": snap.observed_at,
                "reason": "5M_BREAKOUT_OR_VOLUME_NOT_CONFIRMED",
                "snapshot_id": snap.snapshot_id,
            })
            return

        micro_ratio = float(micro.get("volume_ratio") or 0.0)
        micro_structure = bool(micro.get("structure_pass") if "structure_pass" in micro else float(micro.get("close") or 0.0) > float(micro.get("breakout_price") or 0.0))
        micro_volume = bool(micro.get("volume_pass") if "volume_pass" in micro else micro_ratio >= 1.05)
        micro_pass = micro_structure or micro_volume
        micro_strong = micro_structure and micro_volume and micro_ratio >= 1.20
        print(
            f"🟢 FUGLE 5M SUCCESS | {sid} | bars_used={micro.get('bars_used')} "
            f"| structure={'✔' if micro_structure else '✖'} | volume={'✔' if micro_volume else '✖'} "
            f"| volume_ratio={micro_ratio:.2f}x | price_source=LATEST_MIS:{snap.current_price:.2f}",
            flush=True,
        )
        # EARLY is intentionally not gated by projected volume; the volume
        # projection is retained as displayed evidence and STRONG upgrade input.
        if not micro_pass:
            return

        # Do not notify from a stale price that no longer meets the live gate.
        effective = snap.current_price >= float(ctx["breakout_level"]) * (1 + BREAKOUT_BUFFER_PCT / 100)
        live_valid = snap.current_price > snap.today_open and snap.up_pct >= 4.0 and effective and snap.is_traded
        if not live_valid:
            print(f"🟡 SIGNAL NOT SENT | {sid} | latest MIS no longer meets live breakout gate | price={snap.current_price:.2f}", flush=True)
            self.ledger.append_event(ctx["trade_date"], sid, {
                "event_type": "SIGNAL_SUPPRESSED_STALE_TRIGGER",
                "observed_at": snap.observed_at, "snapshot_id": snap.snapshot_id,
                "current_price": snap.current_price, "breakout_level": ctx["breakout_level"],
            })
            return

        projection = self.volume_predictor.project(snap.cumulative_volume_lots, self._as_datetime(snap.observed_at), ctx["vma5_lots"])
        projected_ratio = projection.projected_ratio
        projected_strong = projected_ratio is not None and projected_ratio >= 1.50
        projected_early = projected_ratio is not None and projected_ratio >= 1.30
        trigger = {
            **snap.to_dict(), "k1_high": ctx["k1_high"], "k2_high": ctx["k2_high"],
            "breakout_level": ctx["breakout_level"], "effective_breakout": effective,
            "volume_prediction_pass": projected_early, "fugle_5m_confirmation": micro,
            "early_evidence_source": "FUGLE_5M",
            "state": sm.state.value, "confirmed_snapshots": 2,
            "trigger_to_finalize_ms": max(0.0, (datetime.now(TAIPEI) - self._as_datetime(snap.observed_at)).total_seconds() * 1000),
        }
        vol = {
            "cumulative_volume_lots": snap.cumulative_volume_lots,
            "elapsed_minutes": projection.elapsed_minutes, "projected_volume_lots": projection.projected_volume_lots,
            "projected_ratio": projected_ratio, "baseline_start": projection.baseline_start,
            "baseline_end": projection.baseline_end, "vma5_lots": ctx["vma5_lots"],
            "projection_ready": projection.ready,
        }
        strong_evidence = micro_structure and micro_volume and projected_early
        score = self.prediction_scorer.score(context=ctx, current_price=snap.current_price, up_pct=snap.up_pct,
            projected_ratio=projected_ratio, effective_breakout=effective, confirmed_snapshots=2)
        signal_level = "MOMENTUM" if (float(snap.up_pct) >= 9.5 and micro_strong and projected_strong) else ("STRONG" if strong_evidence else "EARLY")
        trigger["signal_level"] = signal_level
        vol["signal_level"] = signal_level
        trigger["prediction_score"] = score.total
        trigger["prediction_score_breakdown"] = score.to_dict()
        vol["prediction_score_volume_component"] = score.volume
        gate = evaluate_intraday_notification(snap.up_pct).to_dict()
        existing = self.ledger.find_prediction_by_snapshot(ctx["trade_date"], sid, snap.snapshot_id)
        if existing is not None:
            return
        prior_predictions = self.ledger.iter_predictions(ctx["trade_date"])
        evidence_source = str(trigger.get("early_evidence_source", "FUGLE_5M"))
        already_sent_level = any(
            e.get("symbol") == sid
            and str(e.get("trigger_snapshot", {}).get("signal_level", "")).upper() == signal_level
            and str(e.get("trigger_snapshot", {}).get("early_evidence_source", "FUGLE_5M")) == evidence_source
            and self.ledger.notification_status(ctx["trade_date"], sid, e.get("prediction_id")) == "SENT"
            for e in prior_predictions
        )
        if already_sent_level:
            return
        event = self.ledger.create_prediction(ctx, trigger, vol, gate)
        self.events.append(event)
        print(
            f"🟡 INTRADAY_3K_PREDICTION | {sid} | level={signal_level} "
            f"| evidence=FUGLE_5M | price={snap.current_price:.2f} "
            f"| breakout={ctx['breakout_level']:.2f} | projected_ratio={projected_ratio} "
            f"| trigger_age_s={trigger_age:.1f} | snapshot_received_age_s={snapshot_age:.2f}",
            flush=True,
        )
        if gate["should_send"] and self.notifier.enabled:
            telegram_started = time.monotonic()
            telegram_started_at = datetime.now(TAIPEI).isoformat()
            result = self.notifier.send_intraday_prediction(event)
            telegram_elapsed_ms = (time.monotonic() - telegram_started) * 1000
            status = result.get("status", "FAILED")
            print(
                f"📨 TELEGRAM SEND TIMING | {sid} | evidence={evidence_source} | status={status} "
                f"| elapsed_ms={telegram_elapsed_ms:.1f} | started_at={telegram_started_at}",
                flush=True,
            )
            self._record_notification(event_type="INTRADAY_3K_PREDICTION_NOTIFICATION", status=status,
                message_id=result.get("message_id"), prediction_id=event["prediction_id"], symbol=sid, up_pct=snap.up_pct)
            self.ledger.append_event(ctx["trade_date"], sid, {"event_type":"NOTIFICATION", "prediction_id":event["prediction_id"],
                "notification_status":status, "telegram_message_id":result.get("message_id"),
                "sent_at":datetime.now(TAIPEI).isoformat(), "snapshot_id":snap.snapshot_id,
                "current_price":snap.current_price, "signal_level":signal_level})
        else:
            status = "SUPPRESSED" if not gate["should_send"] else "DISABLED"
            self._record_notification(event_type="INTRADAY_3K_PREDICTION_NOTIFICATION", status=status,
                prediction_id=event["prediction_id"], symbol=sid, suppression_reason=gate.get("suppression_reason"), up_pct=snap.up_pct)
            self.ledger.append_event(ctx["trade_date"], sid, {"event_type":"NOTIFICATION", "prediction_id":event["prediction_id"],
                "notification_status":status, "suppression_reason":gate.get("suppression_reason"), "current_price":snap.current_price})
        self._fugle_pending.pop(sid, None)
        self._save_runtime_state()

    def poll_once(self):
        poll_started = time.monotonic()
        previous_start = self._last_radar_cycle_start_monotonic
        start_to_start = (poll_started - previous_start) if previous_start is not None else None
        self._last_radar_cycle_start_monotonic = poll_started
        if start_to_start is not None:
            target_interval = max(1, MIS_INTERVAL_SECONDS)
            print(
                f"📡 RADAR INTERVAL | start_to_start_s={start_to_start:.2f} "
                f"| target_s={target_interval} | overrun_s={max(0.0, start_to_start-target_interval):.2f} "
                f"| previous_cycle_s={self._last_radar_cycle_duration_seconds}",
                flush=True,
            )
        else:
            print(f"📡 RADAR INTERVAL | first_cycle=1 | target_s={max(1, MIS_INTERVAL_SECONDS)}", flush=True)
        # If the premarket lifecycle has already been built and the resulting
        # pool is empty, do not rebuild it on every Radar cycle.  Rebuilding
        # here can unexpectedly invoke daily-refresh/FinMind calendar
        # bootstrap and turns an empty watchlist into a liveness failure.
        if not self.pool:
            if self._premarket_built:
                self._last_radar_cycle_duration_seconds = time.monotonic() - poll_started
                print(
                    f"⏱️ RADAR TIMING | early_return=EMPTY_POOL "
                    f"| cycle_ms={self._last_radar_cycle_duration_seconds * 1000:.1f}",
                    flush=True,
                )
                return 0
            self._load_pool()
        rows = self._radar_rows()
        if not self.universe_cache:
            self.universe_cache = {str(x["symbol"]): x for x in StockUniverseProvider().fetch()}
        # Existing pool + full main-board common-stock universe. MIS remains the
        # only market-wide intraday discovery source; no per-stock FinMind here.
        market_rows = []
        for sid, u in self.universe_cache.items():
            market_rows.append({
                "symbol": sid, "name": u.get("name", ""), "market": u.get("market", ""),
                "product_type": "COMMON_STOCK", "security_type": "COMMON_STOCK", "status": "NORMAL",
                "yesterday_volume_lots": float(u.get("previous_volume_lots") or 0),
            })
        eligible, _ = SnapshotUniverseFilter(min_yesterday_volume_lots=1000).filter_rows(market_rows)
        info = {x["symbol"]: x for x in eligible}
        resolver = lambda s: "otc" if info.get(s, {}).get("market") == "TPEx" else "tse"
        if self.mis_provider is None:
            self.mis_provider = MISProvider(info, resolver)
        else:
            self.mis_provider.stock_info_map = info
            self.mis_provider.exchange_resolver = resolver
        self.recovery.heartbeat("RADAR_FETCHING", success=True)
        pre_fetch_ms = (time.monotonic() - poll_started) * 1000
        fetch_wall_started = time.monotonic()
        try:
            raw = self.mis_provider.fetch_batch()
        except Exception as exc:
            fetch_wall_ms = (time.monotonic() - fetch_wall_started) * 1000
            print(
                f"⏱️ MIS FETCH TIMING | provider_ms=N/A | wall_ms={fetch_wall_ms:.1f} "
                f"| pre_fetch_ms={pre_fetch_ms:.1f} | failed=1", flush=True,
            )
            err = {"error_type": type(exc).__name__, "message": str(exc)[:300]}
            print(f"❌ RADAR ERROR | {err['error_type']} | {err['message']}", flush=True)
            self.recovery.heartbeat("RADAR_ERROR", success=False, error=err)
            self.recovery_ledger.append(self.trade_date or self._today(), {"event_type":"RADAR_ERROR", **err, "at":datetime.now(TAIPEI).isoformat()})
            return 0

        fetch_wall_ms = (time.monotonic() - fetch_wall_started) * 1000
        fetch_stats = getattr(self.mis_provider, "last_fetch_stats", {}) or {}
        if fetch_stats:
            batch_detail = ",".join(
                "{}:{}/{}/{}/{}".format(
                    item.get("batch"), item.get("requested"), item.get("raw_items"),
                    item.get("parsed"), int(bool(item.get("failed"))),
                )
                for item in fetch_stats.get("batch_stats", [])
            )
            print(
                f"⏱️ MIS FETCH TIMING | provider_ms={fetch_stats.get('elapsed_ms', 0)} "
                f"| wall_ms={fetch_wall_ms:.1f} | pre_fetch_ms={pre_fetch_ms:.1f} "
                f"| batches={fetch_stats.get('batches', 0)} | workers={fetch_stats.get('workers', 0)} "
                f"| requested={fetch_stats.get('requested_symbols', 0)} "
                f"| returned={fetch_stats.get('returned_symbols', len(raw))} "
                f"| raw_items={fetch_stats.get('raw_items', 'N/A')} "
                f"| missing_z={fetch_stats.get('missing_last_price', 'N/A')} "
                f"| invalid_y={fetch_stats.get('invalid_previous_close', 'N/A')} "
                f"| missing_symbol={fetch_stats.get('missing_symbol', 'N/A')} "
                f"| quote_time_unknown={fetch_stats.get('quote_time_unknown', 'N/A')} "
                f"| failed_batches={fetch_stats.get('failed_batches', 0)} "
                f"| batch_detail={batch_detail}",
                flush=True,
            )

        # Health checks are also asynchronous: a startup probe must never hold
        # the Radar thread while the market is moving.
        if not self._fugle_health_checked and self.contexts and self._fugle_health_future is None:
            probe_symbol = next(iter(self.contexts))
            print(f"🔵 FUGLE HEALTH CHECK QUEUED | symbol={probe_symbol} | timeframe=5", flush=True)
            self._fugle_health_future = self._fugle_executor.submit(self.fugle_provider.check_5m_access, probe_symbol)
        if self._fugle_health_future is not None and self._fugle_health_future.done():
            future = self._fugle_health_future
            self._fugle_health_future = None
            try:
                result = future.result()
                self._fugle_health_status = "OK" if result.get("ok") else str(result.get("status"))
                print(f"🟢 FUGLE HEALTH CHECK | status={self._fugle_health_status} | bars={result.get('bars', 0)}", flush=True)
            except FugleAPIError as exc:
                self._fugle_health_status = f"HTTP_{exc.status_code or 'ERROR'}"
                print(f"🔴 FUGLE HEALTH CHECK | status={self._fugle_health_status} | symbol={exc.symbol} | {exc.message} | RADAR=CONTINUE", flush=True)
            except Exception as exc:
                self._fugle_health_status = f"ERROR_{type(exc).__name__}"
                print(f"🔴 FUGLE HEALTH CHECK | status={self._fugle_health_status} | {str(exc)[:200]} | RADAR=CONTINUE", flush=True)
            finally:
                self._fugle_health_checked = True
                self._save_runtime_state()

        self._print_radar_monitor(raw, rows)

        # Include MIS network fetch time in the end-to-end Radar timing.
        radar_started = poll_started
        fugle_candidates: set[str] = set()
        state_update_started = time.monotonic()

        # Phase A: update every stock from this MIS snapshot before doing any
        # Fugle work. This is the key non-blocking guarantee for WATCHING,
        # BREAKOUT_PENDING, TRIGGERED and cooldown states.
        raw_symbol_values = fetch_stats.get("raw_symbols")
        fetch_raw_symbols = set(str(x) for x in (raw_symbol_values if raw_symbol_values is not None else raw.keys()))
        fetch_missing_price_symbols = set(str(x) for x in (fetch_stats.get("missing_price_symbols") or []))
        fetch_invalid_y_symbols = set(str(x) for x in (fetch_stats.get("invalid_previous_close_symbols") or []))
        quote_coverage = {
            "monitored": len(self.contexts), "raw_present": 0, "accepted": 0,
            "stale": 0, "invalid": 0, "missing_price": 0,
            "missing_raw": 0, "unknown_time": 0,
        }
        for sid, ctx in list(self.contexts.items()):
            r = raw.get(sid)
            if sid in fetch_raw_symbols:
                quote_coverage["raw_present"] += 1
            if not r:
                if sid in fetch_missing_price_symbols:
                    quote_coverage["missing_price"] += 1
                elif sid in fetch_invalid_y_symbols:
                    quote_coverage["invalid"] += 1
                else:
                    quote_coverage["missing_raw"] += 1
                continue
            try:
                snap = build_snapshot(sid, r, ctx["name"], ctx["market"], "COMMON_STOCK")
            except (TypeError, ValueError, KeyError) as exc:
                quote_coverage["invalid"] += 1
                print(f"🟡 MIS SNAPSHOT INVALID | {sid} | {type(exc).__name__}: {exc}", flush=True)
                continue
            quote_fresh, quote_reason, quote_age = self._mis_quote_freshness(snap)
            if not quote_fresh:
                quote_coverage["stale"] += 1
                quote_coverage["unknown_time"] += int(quote_reason == "QUOTE_TIME_UNKNOWN")
                # Log only quotes that are already pending or could otherwise
                # qualify as a breakout; avoid flooding logs for stale symbols.
                potential_breakout = (
                    snap.current_price >= float(ctx["breakout_level"]) * (1 + BREAKOUT_BUFFER_PCT / 100)
                    and snap.up_pct >= 4.0
                )
                if potential_breakout or sid in self._fugle_pending:
                    print(
                        f"🟠 MIS SNAPSHOT STALE SKIP | {sid} | reason={quote_reason} "
                        f"| quote_age_s={quote_age} | source_time={getattr(snap, 'quote_time', None)}",
                        flush=True,
                    )
                continue
            if snap.current_price <= 0 or snap.previous_close <= 0 or not snap.is_traded:
                quote_coverage["invalid"] += 1
                # Invalid/no-trade quote must not overwrite last valid price or
                # transition the state machine to INVALIDATED.
                print(f"🟡 MIS SNAPSHOT SKIP | {sid} | invalid/no-trade price", flush=True)
                continue
            quote_coverage["accepted"] += 1
            previous_snap = self._latest_snapshots.get(sid)
            self._latest_snapshots[sid] = snap
            self._latest_snapshot_received_at[sid] = time.monotonic()
            # Warm the lightweight volume window continuously for monitored
            # symbols, so a breakout does not have to wait another 45-90s to
            # accumulate its first estimator window. This is memory-only work.
            estimator = getattr(self, "mis_live_volume", None)
            if estimator is not None:
                try:
                    estimator.observe(sid, snap.observed_at, snap.cumulative_volume_lots, float(ctx.get("vma5_lots") or 0.0))
                except (TypeError, ValueError):
                    pass
            sm = self.states.setdefault(sid, IntradayStateMachine())
            triggered, reason = sm.evaluate(
                snap, ctx["breakout_level"], 4.0, BREAKOUT_BUFFER_PCT
            )
            if reason == "DUPLICATE_SNAPSHOT":
                # Latest quote is still stored above, but duplicate identity
                # cannot advance the state machine or count as confirmation.
                if sm.state.value == "TRIGGERED" and sid in self._fugle_pending:
                    fugle_candidates.add(sid)
                continue
            if reason == "TRIGGER_INVALIDATED":
                self._fugle_pending.pop(sid, None)
                self._expired_trigger_logged.discard(sid)
            self.ledger.append_event(ctx["trade_date"], sid, {
                "event_type": "RADAR_STATE",
                "observed_at": snap.observed_at,
                "state": sm.state.value,
                "reason": reason,
                "snapshot_id": snap.snapshot_id,
                "data_identity": snap.data_identity,
                "current_price": snap.current_price,
            })
            if triggered:
                self._expired_trigger_logged.discard(sid)
                # TTL starts when this process confirms the trigger, not from
                # a provider/source timestamp that may be stale or replayed.
                self._fugle_pending[sid] = datetime.now(TAIPEI).isoformat()
                print(
                    f"🔔 BREAKOUT TRIGGER | {sid} {ctx['name']} | price={snap.current_price:.2f} "
                    f"| breakout={ctx['breakout_level']:.2f} | snapshot={snap.snapshot_id}",
                    flush=True,
                )
                fugle_candidates.add(sid)
                self._finalize_mis_early(sid, ctx, snap, previous_snap)
            elif sm.state.value == "TRIGGERED" and sid in self._fugle_pending:
                fugle_candidates.add(sid)
                self._finalize_mis_early(sid, ctx, snap, previous_snap)

        state_update_ms = (time.monotonic() - state_update_started) * 1000
        print(
            f"📊 MIS QUOTE COVERAGE | monitored={quote_coverage['monitored']} "
            f"| raw_present={quote_coverage['raw_present']} | accepted={quote_coverage['accepted']} "
            f"| stale={quote_coverage['stale']} | unknown_time={quote_coverage['unknown_time']} "
            f"| invalid={quote_coverage['invalid']} | missing_price={quote_coverage['missing_price']} "
            f"| missing_raw={quote_coverage['missing_raw']}",
            flush=True,
        )
        print(
            f"⏱️ RADAR PHASE | state_update_ms={state_update_ms:.1f} "
            f"| latest_snapshots={len(self._latest_snapshots)} | fugle_inflight={len(self._fugle_futures)}",
            flush=True,
        )

        # Phase B: consume completed Fugle jobs. Use the newest valid MIS
        # snapshot, not the snapshot captured before the HTTP request began.
        for sid, future in list(self._fugle_futures.items()):
            if not future.done():
                continue
            self._fugle_futures.pop(sid, None)
            ctx = self.contexts.get(sid)
            if not ctx:
                continue
            try:
                micro = future.result()
            except FugleAPIError as exc:
                print(f"🔴 FUGLE 5M ERROR | {sid} | HTTP={exc.status_code or 'N/A'} | {exc.message} | ACTION=RETRY", flush=True)
                self.ledger.append_event(ctx["trade_date"], sid, {
                    "event_type": "FUGLE_5M_ERROR", "observed_at": datetime.now(TAIPEI).isoformat(),
                    "status_code": exc.status_code, "reason": exc.message,
                })
                self._save_runtime_state()
                continue
            except Exception as exc:
                print(f"🔴 FUGLE 5M UNEXPECTED ERROR | {sid} | {type(exc).__name__} | {str(exc)[:300]} | ACTION=RETRY", flush=True)
                self.ledger.append_event(ctx["trade_date"], sid, {
                    "event_type": "FUGLE_5M_ERROR", "observed_at": datetime.now(TAIPEI).isoformat(),
                    "status_code": None, "reason": f"{type(exc).__name__}: {str(exc)[:300]}",
                })
                self._save_runtime_state()
                continue
            latest = self._latest_snapshots.get(sid)
            if latest is None:
                print(f"🟡 FUGLE RESULT STALE | {sid} | no latest MIS snapshot", flush=True)
                continue
            # A trigger that has already invalidated must not be resurrected by
            # a delayed Fugle response. Newest quote remains the source of price.
            if self.states.get(sid) and self.states[sid].state.value != "TRIGGERED":
                print(f"🟡 FUGLE RESULT DISCARDED | {sid} | state={self.states[sid].state.value}", flush=True)
                continue
            self._finalize_fugle_result(sid, ctx, latest, micro)

        # Phase C: schedule new/retry confirmations. Never wait for them here;
        # next MIS Radar cycle can begin on time while these requests are in flight.
        schedule_started = time.monotonic()
        now_mono = time.monotonic()
        for sid in sorted(fugle_candidates):
            if sid in self._fugle_futures or sid not in self._fugle_pending:
                continue
            trigger_age = self._pending_trigger_age_seconds(sid)
            if trigger_age > FUGLE_PENDING_TTL_SECONDS:
                if sid not in self._expired_trigger_logged:
                    print(
                        f"🟠 FUGLE RETRY EXPIRED | {sid} | trigger_age_s={trigger_age:.1f} "
                        f"| ttl_s={FUGLE_PENDING_TTL_SECONDS} | stop repeated API requests",
                        flush=True,
                    )
                    self._expired_trigger_logged.add(sid)
                continue
            last_attempt = self._fugle_last_attempt.get(sid, 0.0)
            if now_mono - last_attempt < self._fugle_retry_seconds:
                continue
            self._fugle_last_attempt[sid] = now_mono
            snap = self._latest_snapshots.get(sid)
            snapshot_id = getattr(snap, "snapshot_id", "N/A")
            print(f"🔵 FUGLE 5M QUEUED | {sid} | snapshot={snapshot_id} | workers=4", flush=True)
            self._fugle_futures[sid] = self._fugle_executor.submit(
                self._timed_fugle_evaluate, sid
            )
        schedule_ms = (time.monotonic() - schedule_started) * 1000

        # Dynamic discovery/history enrichment runs only after the current
        # market snapshot has updated all existing states and pending Fugle
        # work has been serviced. It can no longer delay this cycle's quote
        # updates or a ready-to-send notification.
        discovery_started = time.monotonic()
        dynamic_candidates = self._dynamic_candidate_gate(raw, self.universe_cache)
        added = self._enrich_dynamic_candidates(dynamic_candidates)
        if added:
            self._save_dynamic_candidates()
        discovery_ms = (time.monotonic() - discovery_started) * 1000
        print(
            f"🧭 DYNAMIC DISCOVERY | candidates={len(dynamic_candidates)} "
            f"| enriched={added} | active={len(self.dynamic_contexts)} "
            f"| history_budget/cycle={self.dynamic_discovery_config.max_history_enrich_per_cycle} "
            f"| cooldown_skipped={getattr(self, '_last_dynamic_cooldown_skipped', 0)} "
            f"| elapsed_ms={discovery_ms:.1f}",
            flush=True,
        )
        cycle_ms = (time.monotonic() - radar_started) * 1000
        self._last_radar_cycle_duration_seconds = cycle_ms / 1000.0
        print(
            f"⏱️ RADAR TIMING | pre_fetch_ms={pre_fetch_ms:.1f} "
            f"| mis_fetch_wall_ms={fetch_wall_ms:.1f} | state_update_ms={state_update_ms:.1f} "
            f"| fugle_schedule_ms={schedule_ms:.1f} | cycle_ms={cycle_ms:.1f} "
            f"| fugle_inflight={len(self._fugle_futures)}",
            flush=True,
        )
        self._save_runtime_state()

        self.recovery.heartbeat("RADAR_COMPLETE", success=True)
        self.recovery_ledger.append(self.trade_date or self._today(), {"event_type":"RADAR_COMPLETE", "snapshot_count":len(raw), "at":datetime.now(TAIPEI).isoformat()})
        return len(raw)

    def _load_pool_from_memory(self):
        s1_path = self.cache / "stage1_trend.json"
        s1 = json.loads(s1_path.read_text(encoding="utf-8")) if s1_path.exists() else []
        s1 = {str(x["symbol"]): x for x in s1}
        u = {x["symbol"]: x for x in StockUniverseProvider().fetch()}
        self.contexts = {}
        self.states = {}
        self.events = self._load_today_predictions()
        for x in self.pool:
            sid = str(x["symbol"])
            t = s1.get(sid, {})
            self.contexts[sid] = {
                "trade_date": self.trade_date, "symbol": sid,
                "name": u.get(sid, {}).get("name", x.get("name", "")),
                "market": u.get(sid, {}).get("market", x.get("market", "")),
                "industry": u.get(sid, {}).get("industry", ""),
                "source_data_date": x.get("date") or x.get("latest_date") or self.latest_completed_date,
                "previous_close": float(x.get("close") or 0),
                "k1_high": float(x.get("k1_high") or 0), "k2_high": float(x.get("k2_high") or 0),
                "breakout_level": float(x.get("breakout_level") or 0),
                "ma20": float(t.get("ma20") or 0), "ma60": float(t.get("ma60") or 0),
                "ma20_prev": float(t.get("ma20_prev") or 0),
                "vma5_lots": float(x.get("stage3", {}).get("vma5_lots") or x.get("vma5_lots") or 0),
                "yesterday_volume_lots": float(x.get("stage3", {}).get("yesterday_volume_lots") or x.get("yesterday_volume_lots") or 0),
                "stage0_pass": True, "stage1_pass": True, "stage2_pass": True, "stage3_pass": True, "final_pool": True,
            }
            self.states[sid] = IntradayStateMachine()
            self.ledger.write_context(self.contexts[sid])
        self._load_dynamic_candidates()
        self._load_runtime_state()
        # Reconstruct state from the durable ledger when the process died
        # between a prediction/event write and the runtime checkpoint.
        for sid in self.contexts:
            sm = self.states.setdefault(sid, IntradayStateMachine())
            events = self.ledger.events_for_symbol(self.trade_date, sid)
            state_events = [e for e in events if e.get("event_type") == "RADAR_STATE"]
            if state_events:
                last = state_events[-1]
                try:
                    sm.state = sm.state.__class__(last.get("state", sm.state.value))
                except ValueError:
                    pass
                sm.last_snapshot_id = str(last.get("snapshot_id") or sm.last_snapshot_id)
            predictions = [e for e in events if e.get("event_type") == "INTRADAY_3K_PREDICTION"]
            if predictions:
                sm.state = sm.state.__class__.TRIGGERED
                sm.trigger_count = max(sm.trigger_count, len(predictions))
                last_pred = predictions[-1]
                sm.last_snapshot_id = str(last_pred.get("trigger_snapshot", {}).get("snapshot_id") or sm.last_snapshot_id)
                sm.last_data_identity = str(last_pred.get("trigger_snapshot", {}).get("data_identity") or sm.last_data_identity)
                sm.last_trigger_price = float(last_pred.get("trigger_snapshot", {}).get("current_price") or sm.last_trigger_price or 0)

    def reconcile_pending_notifications(self) -> int:
        """Retry only predictions whose durable ledger lacks a successful send.

        This closes the crash window: prediction is persisted first, Telegram second.
        Restart can safely resend a prediction whose notification was never confirmed.
        """
        if not self.trade_date or not self.notifier.enabled:
            return 0
        resent = 0
        for event in self.ledger.iter_predictions(self.trade_date):
            sid = str(event.get("symbol"))
            status = self.ledger.notification_status(self.trade_date, sid, event["prediction_id"])
            if status in {"SENT", "SUPPRESSED"}:
                continue
            gate = event.get("notification", {})
            if gate.get("should_send") is False:
                continue
            result = self.notifier.send_intraday_prediction(event)
            self.ledger.append_event(self.trade_date, sid, {
                "event_type":"NOTIFICATION",
                "prediction_id":event["prediction_id"],
                "notification_status":result.get("status", "FAILED"),
                "telegram_message_id":result.get("message_id"),
                "recovered":True,
                "sent_at":datetime.now(TAIPEI).isoformat(),
            })
            self._record_notification(
                event_type="INTRADAY_3K_PREDICTION_NOTIFICATION",
                status=result.get("status", "FAILED"),
                message_id=result.get("message_id"),
                prediction_id=event["prediction_id"],
                symbol=sid,
                recovered=True,
            )
            if result.get("status") == "SENT":
                resent += 1
        return resent

    def _load_pool(self):
        self.trade_date = self._today()
        self._set_runtime_path()
        daily_pool = self.cache / "pools" / f"{self.trade_date}.json"
        if not daily_pool.exists():
            self.build_premarket_pool(self.trade_date)
            return
        self.pool = json.loads(daily_pool.read_text(encoding="utf-8"))
        # A fresh process may not have run the premarket initialization in
        # this process, so restore the T-1 completed-K date from the durable
        # pool before dynamic history enrichment.
        dates = [str(x.get("date") or x.get("latest_date") or "") for x in self.pool]
        dates = [d for d in dates if d]
        if dates:
            self.latest_completed_date = max(dates)
        else:
            freshness_path = self.cache / "data_freshness.json"
            if freshness_path.exists():
                try:
                    self.latest_completed_date = json.loads(freshness_path.read_text(encoding="utf-8")).get("latest_completed_date")
                except Exception:
                    pass
        self._load_pool_from_memory()

    def _finalize_close_snapshot(self, trade_date: str | None = None) -> dict:
        """Finalize the official daily close snapshot without using FinMind.

        This compatibility/close-finalization boundary intentionally delegates
        to the official TWSE/TPEx daily snapshot provider.  It is idempotent
        and does not consume the FinMind request budget.
        """
        td = trade_date or self.trade_date or self._today()
        result = self.data_refresh.refresh_official_daily(td)
        self.recovery_ledger.append(td, {
            "event_type": "OFFICIAL_CLOSE_SNAPSHOT_FINALIZED",
            "status": result.get("status"),
            "twse_rows": result.get("twse_rows", 0),
            "tpex_rows": result.get("tpex_rows", 0),
            "rows_written": result.get("rows_written", 0),
            "at": datetime.now(TAIPEI).isoformat(),
        })
        return result

    def _fetch_ground_truth_for_symbol(self, sid: str, td: str, ctx: dict) -> dict | None:
        if not FUGLE_API_KEY:
            self._ground_truth_failure_reasons = getattr(self, "_ground_truth_failure_reasons", {})
            self._ground_truth_failure_reasons[str(sid)] = "MISSING_FUGLE_API_KEY"
            if not self.ledger.has_event(td, str(sid), "GROUND_TRUTH_UNAVAILABLE"):
                self.ledger.append_event(td, sid, {
                    "event_type": "GROUND_TRUTH_UNAVAILABLE",
                    "reason": "MISSING_FUGLE_API_KEY",
                    "at": datetime.now(TAIPEI).isoformat(),
                })
            return None
        try:
            params = {"fields": "open,high,low,close,volume", "timeframe": "D"}
            headers = {"X-API-KEY": FUGLE_API_KEY}
            r = requests.get(
                f"https://api.fugle.tw/marketdata/v1.0/stock/historical/candles/{sid}",
                headers=headers, params=params, timeout=12,
            )
            r.raise_for_status()
            payload = r.json()
            data = payload.get("candles", payload.get("data", []))
            rows = [x for x in data if x.get("date") and str(x["date"])[:10] <= td]
            rows = sorted(rows, key=lambda x: str(x["date"]))
            if len(rows) < 6:
                reason = f"INSUFFICIENT_DAILY_CANDLES:{len(rows)}"
                self._ground_truth_failure_reasons = getattr(self, "_ground_truth_failure_reasons", {})
                self._ground_truth_failure_reasons[str(sid)] = reason
                if not self.ledger.has_event(td, str(sid), "GROUND_TRUTH_UNAVAILABLE"):
                    self.ledger.append_event(td, sid, {
                        "event_type": "GROUND_TRUTH_UNAVAILABLE",
                        "reason": reason,
                        "at": datetime.now(TAIPEI).isoformat(),
                    })
                return None
            k0, k1, k2 = rows[-1], rows[-2], rows[-3]
            gain = float(k0["close"]) / float(k1["close"]) - 1
            vols = [float(x["volume"]) / 1000 for x in rows[-6:]]
            vma5 = sum(vols[:-1]) / 5
            vr = vols[-1] / vma5 if vma5 else 0
            s2 = bool(
                float(k0["close"]) > float(k0["open"])
                and gain >= 0.04
                and float(k0["high"]) > float(k1["high"])
                and float(k0["high"]) > float(k2["high"])
                and float(k0["close"]) > max(float(k1["high"]), float(k2["high"]))
            )
            s3 = bool(vma5 >= 1000 and vols[-1] > vols[-2] and vr >= 1.5)
            return {
                "trade_date": td,
                "symbol": sid,
                "close": float(k0["close"]),
                "high": float(k0["high"]),
                "low": float(k0["low"]),
                "gain_pct": gain * 100,
                "volume_lots": vols[-1],
                "yesterday_volume_lots": vols[-2],
                "vma5_lots": vma5,
                "volume_ratio": vr,
                "stage1_pass": bool(ctx["stage1_pass"]),
                "stage2_pass": s2,
                "stage3_pass": s3,
                "ground_truth_3k": bool(ctx["stage1_pass"] and s2 and s3),
                "validated_at": datetime.now(TAIPEI).isoformat(),
            }
        except Exception as exc:
            reason = f"API_ERROR:{type(exc).__name__}"
            self._ground_truth_failure_reasons = getattr(self, "_ground_truth_failure_reasons", {})
            self._ground_truth_failure_reasons[str(sid)] = reason
            self.ledger.append_event(td, sid, {
                "event_type": "GROUND_TRUTH_ERROR",
                "error_type": type(exc).__name__,
                "message": str(exc)[:300],
                "at": datetime.now(TAIPEI).isoformat(),
            })
            return None

    def _read_persisted_ground_truth(self, trade_date: str, symbol: str):
        """Return a durable same-day Ground Truth row, if already available."""
        path = self.ledger._dir(trade_date, symbol) / "ground_truth.json"
        if not path.exists():
            return None
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
            if str(row.get("trade_date")) == str(trade_date) and str(row.get("symbol")) == str(symbol):
                return row
        except (OSError, ValueError, TypeError):
            return None
        return None

    def _missing_prediction_ground_truth_symbols(self, trade_date: str):
        """Return unresolved prediction symbols; None means there are no predictions."""
        predictions = [e for e in self.ledger.iter_predictions(trade_date)
                       if e.get("event_type") == "INTRADAY_3K_PREDICTION"]
        if not predictions:
            return None
        required = {str(e.get("symbol")) for e in predictions}
        missing = set()
        for sid in required:
            persisted = self._read_persisted_ground_truth(trade_date, sid)
            if not persisted or persisted.get("ground_truth_3k") is None:
                missing.add(sid)
        return missing

    def _prediction_ground_truth_complete(self, trade_date: str, rows=None) -> bool:
        """Completion is based on all predictions needing validation, not any one row."""
        missing = self._missing_prediction_ground_truth_symbols(trade_date)
        if missing is None:
            return bool(rows)
        return not missing

    def _finalize_unavailable_prediction_validations(self, trade_date: str):
        """At the 13:35 cutoff, durably mark predictions still lacking Ground Truth."""
        predictions = [e for e in self.ledger.iter_predictions(trade_date)
                       if e.get("event_type") == "INTRADAY_3K_PREDICTION"]
        missing = 0
        for event in predictions:
            sid = str(event.get("symbol"))
            gt = self._read_persisted_ground_truth(trade_date, sid)
            if gt and gt.get("ground_truth_3k") is not None:
                continue
            event_path = self.ledger._dir(trade_date, sid) / "events.jsonl"
            existing = self.ledger.read_jsonl(event_path)
            matching = [x for x in existing if x.get("event_type") == "PREDICTION_VALIDATION"
                        and x.get("prediction_id") == event.get("prediction_id")]
            if any(x.get("ground_truth_available") is False for x in matching):
                continue
            if any(x.get("ground_truth_available") is True for x in matching):
                continue
            row = {
                "event_type": "PREDICTION_VALIDATION",
                "prediction_id": event.get("prediction_id"),
                "trade_date": trade_date,
                "symbol": sid,
                "prediction_created_at": event.get("created_at"),
                "prediction_notification_status": event.get("notification_status"),
                "ground_truth_available": False,
                "ground_truth_3k": None,
                "validation_status": "GROUND_TRUTH_UNAVAILABLE_AT_CUTOFF",
                "validated_at": datetime.now(TAIPEI).isoformat(),
            }
            self.ledger.append_event(trade_date, sid, row)
            self.ledger._append(self.ledger.validation_root / "master_prediction_validation_log.jsonl", row)
            missing += 1
        self.ledger.append_daily_event(trade_date, {
            "event_type": "GROUND_TRUTH_CUTOFF_VALIDATION_SUMMARY",
            "prediction_count": len(predictions),
            "unavailable_count": missing,
            "at": datetime.now(TAIPEI).isoformat(),
        })
        print(f"🧾 GROUND_TRUTH CUTOFF VALIDATION | predictions={len(predictions)} | unavailable={missing}", flush=True)

    def ground_truth(self, trade_date: str | None = None, symbols: set[str] | None = None):
        td = trade_date or self.trade_date or self._today()
        started = time.monotonic()
        selected_contexts = [(sid, ctx) for sid, ctx in self.contexts.items()
                             if symbols is None or str(sid) in symbols]
        print(f"🧾 GROUND_TRUTH START | trade_date={td} | contexts={len(self.contexts)} "
              f"| selected={len(selected_contexts)} | retry_scope={'ALL' if symbols is None else 'PREDICTIONS'}", flush=True)
        results = []
        attempted = 0
        cached = 0
        missing_reasons = {}
        self._ground_truth_failure_reasons = getattr(self, "_ground_truth_failure_reasons", {})
        for sid, ctx in selected_contexts:
            gt = self._read_persisted_ground_truth(td, str(sid))
            if gt is not None:
                cached += 1
            else:
                attempted += 1
                gt = self._fetch_ground_truth_for_symbol(sid, td, ctx)
                if gt is None:
                    missing_reasons[str(sid)] = self._ground_truth_failure_reasons.get(str(sid), "NO_VALID_RESULT")
                    continue
                self.ledger.write_ground_truth(td, sid, gt)
            results.append(gt)

        # Keep previously completed same-day rows in the result set even when
        # this retry only targets unresolved prediction symbols.
        result_symbols = {str(x.get("symbol")) for x in results}
        for sid in self.contexts:
            if str(sid) in result_symbols:
                continue
            cached_gt = self._read_persisted_ground_truth(td, str(sid))
            if cached_gt is not None:
                results.append(cached_gt)
                result_symbols.add(str(sid))

        self.ground_truth = results
        gt_map = {str(x["symbol"]): x for x in results}
        validation_rows = []
        predictions = list(self.ledger.iter_predictions(td))
        self.events = predictions
        for event in predictions:
            if event.get("event_type") != "INTRADAY_3K_PREDICTION":
                continue
            sid = str(event["symbol"])
            gt = gt_map.get(sid) or self._read_persisted_ground_truth(td, sid)
            if gt is None:
                # Do not freeze a missing-data result during the retry window.
                # The cutoff handler will record unavailable validation only
                # after all Ground Truth retries have ended.
                continue
            row = self.prediction_chain.validate_prediction(event, gt)
            validation_rows.append(row)
            event_path = self.ledger._dir(td, sid) / "events.jsonl"
            existing = self.ledger.read_jsonl(event_path)
            matching = [x for x in existing if x.get("event_type") == "PREDICTION_VALIDATION"
                        and x.get("prediction_id") == row["prediction_id"]]
            if not any(x.get("ground_truth_available") is True for x in matching):
                self.ledger.append_event(td, sid, {
                    "event_type": "PREDICTION_VALIDATION",
                    **row,
                })
                self.ledger._append(self.ledger.validation_root / "master_prediction_validation_log.jsonl", row)

        self.validation_rows = validation_rows
        daily_events_path = self.ledger.validation_root / "daily_events" / f"{td}.jsonl"
        durable_daily_events = self.ledger.read_jsonl(daily_events_path)
        report_events = self.events + durable_daily_events
        report = build_daily_report(td, self.pool, report_events, results, validation_rows)
        write_daily_report(self.tianji / "validation", td, report)

        try:
            calibration_engine = PredictionCalibrationEngine()
            daily_calibration = calibration_engine.build_from_ledger(self.pred_root, td)
            calibration_engine.write_report(
                self.tianji / "validation" / f"score_calibration_{td}.json",
                daily_calibration,
            )
            calibration = calibration_engine.build_from_ledger(self.pred_root, None)
            calibration_engine.write_report(
                self.tianji / "validation" / "score_calibration.json", calibration
            )
            self.ledger.append_daily_event(td, {
                "event_type": "PREDICTION_CALIBRATION_UPDATED",
                "daily_matched_count": daily_calibration.get("matched_count", 0),
                "daily_hit_count": daily_calibration.get("hit_count", 0),
                "cumulative_matched_count": calibration.get("matched_count", 0),
                "cumulative_hit_count": calibration.get("hit_count", 0),
                "cumulative_empirical_hit_rate": calibration.get("empirical_hit_rate"),
                "at": datetime.now(TAIPEI).isoformat(),
            })
        except Exception as exc:
            self.ledger.append_daily_event(td, {
                "event_type": "PREDICTION_CALIBRATION_ERROR",
                "error_type": type(exc).__name__,
                "message": str(exc)[:300],
                "at": datetime.now(TAIPEI).isoformat(),
            })

        predicted_symbols = {str(e["symbol"]) for e in predictions if e.get("event_type") == "INTRADAY_3K_PREDICTION"}
        for gt in results:
            if str(gt["symbol"]) not in predicted_symbols or not self.notifier.enabled:
                continue
            if self.ledger.has_event(td, str(gt["symbol"]), "GROUND_TRUTH_NOTIFICATION"):
                continue
            result = self.notifier.send_ground_truth(gt)
            gt_event = {
                "event_type": "GROUND_TRUTH_NOTIFICATION",
                "status": result.get("status", "FAILED"),
                "telegram_message_id": result.get("message_id"),
                "symbol": str(gt["symbol"]),
                "ground_truth_3k": gt["ground_truth_3k"],
                "sent_at": datetime.now(TAIPEI).isoformat(),
            }
            self.ledger.append_event(td, str(gt["symbol"]), gt_event)
            self._record_notification(**gt_event)

        missing_prediction_symbols = sorted(predicted_symbols - set(gt_map))
        elapsed = time.monotonic() - started
        print(
            f"🧾 GROUND_TRUTH RESULT | trade_date={td} | contexts={len(self.contexts)} "
            f"| attempted={attempted} | cached={cached} | success={len(results)} "
            f"| predictions={len(predictions)} | validated={len(validation_rows)} "
            f"| missing_prediction_symbols={','.join(missing_prediction_symbols) or '-'} "
            f"| missing_reasons={
(
    ';'.join(
        '{}:{}'.format(
            sid,
            missing_reasons.get(
                sid,
                self._ground_truth_failure_reasons.get(
                    sid, "PERSISTED_NOT_FOUND"
                ),
            ),
        )
        for sid in missing_prediction_symbols
    )
    or '-'
)
} "
            f"| complete={self._prediction_ground_truth_complete(td, results)} | elapsed_s={elapsed:.2f}",
            flush=True,
        )
        return results

    def run_forever(self, manual_monitor: bool = False):
        """Run one complete trading-day production lifecycle.

        The ledger is the source of truth; runtime_state/checkpoint are only
        recovery aids. Every phase is idempotent so a restart resumes safely.
        """
        now = datetime.now(TAIPEI)
        # Production mode remains strictly session-gated. Manual monitor mode
        # is an explicit operator/test mode: it never exits merely because the
        # current clock is outside the Taiwan trading session.
        if not manual_monitor and not self.session.is_trading_candidate(now.date()):
            print(f"TIANJI CLOSED | {now.date().isoformat()}")
            return 0

        self.process_lock.acquire()
        try:
            trade_date = now.date().isoformat()
            self.trade_date = trade_date
            self._set_runtime_path()
            prior = self.recovery.status()
            recovered = bool(
                prior.get("trade_date") == trade_date
                and not prior.get("clean_shutdown", False)
                and (not prior.get("last_poll_at") or self.recovery.recovery_needed(stale_seconds=120))
            )
            self.recovery.start(trade_date, "STARTING")
            print("=" * 72, flush=True)
            print(f"🚀 TIANJI 3K PRODUCTION START | trade_date={trade_date}", flush=True)
            print(f"📡 RADAR interval={MIS_INTERVAL_SECONDS}s | Telegram={'ON' if self.notifier.enabled else 'OFF'} | Dynamic Discovery=ON", flush=True)
            if manual_monitor:
                print("🧪 MANUAL MONITOR MODE | 忽略非盤中時間限制 | 僅供本地/線上測試，不代表目前為真實盤中", flush=True)
                print("🧭 啟動後會持續執行 MIS Radar，並列出目前實際進入監控的股票", flush=True)
            print("=" * 72, flush=True)
            if recovered:
                self.recovery_ledger.append(trade_date, {
                    "event_type": "RECOVERY_DETECTED",
                    "checkpoint": self.recovery.status(),
                    "at": datetime.now(TAIPEI).isoformat(),
                })

            gt_done = False
            gt_first_pass_done = False
            while True:
                now = datetime.now(TAIPEI)
                phase = self.session.phase(now)

                if manual_monitor:
                    if phase != getattr(self, "_last_phase", None):
                        print(f"🧪 MANUAL PHASE | TradingSession={phase} | {now.strftime('%H:%M:%S')}", flush=True)
                        self._last_phase = phase
                    if not self.pool:
                        try:
                            self._load_pool()
                        except Exception as exc:
                            err = {"error_type": type(exc).__name__, "message": str(exc)[:300]}
                            print(f"❌ MANUAL MONITOR INIT ERROR | {err['error_type']} | {err['message']}", flush=True)
                            self.recovery.heartbeat("MANUAL_MONITOR_INIT_ERROR", success=False, error=err)
                            time.sleep(MIS_INTERVAL_SECONDS)
                            continue
                    self._load_runtime_state()
                    try:
                        cycle_started = time.monotonic()
                        self.poll_once()
                        self._next_radar_deadline = max(
                            self._next_radar_deadline, cycle_started
                        ) + MIS_INTERVAL_SECONDS
                    except Exception as exc:
                        self._last_radar_cycle_duration_seconds = time.monotonic() - cycle_started
                        err = {"error_type": type(exc).__name__, "message": str(exc)[:300]}
                        print(
                            f"❌ MANUAL RADAR ERROR | {err['error_type']} | {err['message']} "
                            f"| cycle_s={self._last_radar_cycle_duration_seconds:.2f}", flush=True,
                        )
                        self.recovery.heartbeat("MANUAL_RADAR_ERROR", success=False, error=err)
                    schedule_now = time.monotonic()
                    delay = max(0.5, self._next_radar_deadline - schedule_now)
                    cycle_elapsed = schedule_now - cycle_started
                    deadline_lag = max(0.0, schedule_now - self._next_radar_deadline)
                    print(
                        f"⏲️ RADAR SCHEDULE | mode=MANUAL | cycle_s={cycle_elapsed:.2f} "
                        f"| target_s={MIS_INTERVAL_SECONDS} | sleep_s={min(delay, MIS_INTERVAL_SECONDS):.2f} "
                        f"| deadline_lag_s={deadline_lag:.2f}", flush=True,
                    )
                    time.sleep(min(delay, MIS_INTERVAL_SECONDS))
                    continue

                if phase != getattr(self, "_last_phase", None):
                    print(f"🟢 PHASE -> {phase} | {now.strftime('%H:%M:%S')}", flush=True)
                    self._last_phase = phase
                if phase == "PREMARKET_WAIT":
                    self.recovery.heartbeat("WAITING_PREMARKET", success=True)
                    time.sleep(min(30, MIS_INTERVAL_SECONDS))
                    continue
                if phase == "PREMARKET":
                    if not self.pool:
                        try:
                            self.build_premarket_pool(trade_date)
                        except Exception as exc:
                            err = {"error_type": type(exc).__name__, "message": str(exc)[:300]}
                            self.recovery.heartbeat("PREMARKET_BUILD_ERROR", success=False, error=err)
                            self.recovery_ledger.append(trade_date, {"event_type": "PREMARKET_BUILD_ERROR", **err, "at": datetime.now(TAIPEI).isoformat()})
                    else:
                        self._load_runtime_state()
                    time.sleep(min(30, MIS_INTERVAL_SECONDS))
                    continue
                if phase == "RADAR":
                    if self._next_radar_deadline <= time.monotonic():
                        self._next_radar_deadline = time.monotonic()
                    if not self.pool:
                        try:
                            self.build_premarket_pool(trade_date)
                        except Exception as exc:
                            err = {"error_type": type(exc).__name__, "message": str(exc)[:300]}
                            self.recovery.heartbeat("RADAR_POOL_BUILD_ERROR", success=False, error=err)
                            self.recovery_ledger.append(trade_date, {"event_type": "RADAR_POOL_BUILD_ERROR", **err, "at": datetime.now(TAIPEI).isoformat()})
                            time.sleep(MIS_INTERVAL_SECONDS)
                            continue
                    self._load_runtime_state()
                    try:
                        cycle_started = time.monotonic()
                        self.poll_once()
                        # Fixed-cadence radar: work time is included in the
                        # interval so a slow cycle does not drift to 30-40s.
                        self._next_radar_deadline = max(
                            self._next_radar_deadline, cycle_started
                        ) + MIS_INTERVAL_SECONDS
                    except Exception as exc:
                        self._last_radar_cycle_duration_seconds = time.monotonic() - cycle_started
                        err = {"error_type": type(exc).__name__, "message": str(exc)[:300]}
                        print(
                            f"❌ RADAR FATAL ERROR | {err['error_type']} | {err['message']} "
                            f"| cycle_s={self._last_radar_cycle_duration_seconds:.2f}", flush=True,
                        )
                        self.recovery.heartbeat("RADAR_FATAL_ERROR", success=False, error=err)
                        self.recovery_ledger.append(trade_date, {"event_type": "RADAR_FATAL_ERROR", **err, "at": datetime.now(TAIPEI).isoformat()})
                    now_ts = time.monotonic()
                    if now_ts - self._last_notification_retry_at >= 60:
                        self.reconcile_pending_notifications()
                        self._last_notification_retry_at = now_ts
                    schedule_now = time.monotonic()
                    delay = max(0.5, self._next_radar_deadline - schedule_now)
                    cycle_elapsed = schedule_now - cycle_started
                    deadline_lag = max(0.0, schedule_now - self._next_radar_deadline)
                    print(
                        f"⏲️ RADAR SCHEDULE | mode=PRODUCTION | cycle_s={cycle_elapsed:.2f} "
                        f"| target_s={MIS_INTERVAL_SECONDS} | sleep_s={min(delay, MIS_INTERVAL_SECONDS):.2f} "
                        f"| deadline_lag_s={deadline_lag:.2f}", flush=True,
                    )
                    time.sleep(min(delay, MIS_INTERVAL_SECONDS))
                    continue
                if phase == "GROUND_TRUTH":
                    if not self.pool:
                        self._load_pool()
                    # Ground truth can require several minutes after the bell to
                    # become available from the data provider. Retry every 20s.
                    if not gt_done:
                        try:
                            retry_symbols = None if not gt_first_pass_done else self._missing_prediction_ground_truth_symbols(trade_date)
                            rows = self.ground_truth(symbols=retry_symbols)
                            gt_first_pass_done = True
                            gt_done = self._prediction_ground_truth_complete(trade_date, rows)
                        except Exception as exc:
                            self.recovery.heartbeat("GROUND_TRUTH_ERROR", success=False, error={"error_type": type(exc).__name__, "message": str(exc)[:300]})
                            print(f"❌ GROUND_TRUTH ERROR | {type(exc).__name__} | {str(exc)[:300]}", flush=True)
                        if not gt_done:
                            time.sleep(MIS_INTERVAL_SECONDS)
                            continue
                    time.sleep(5)
                    continue
                if phase == "STOP":
                    if not gt_done:
                        try:
                            retry_symbols = self._missing_prediction_ground_truth_symbols(trade_date) if gt_first_pass_done else None
                            rows = self.ground_truth(symbols=retry_symbols)
                            gt_first_pass_done = True
                            gt_done = self._prediction_ground_truth_complete(trade_date, rows)
                        except Exception as exc:
                            self.recovery_ledger.append(trade_date, {"event_type":"GROUND_TRUTH_CUTOFF_ERROR", "error_type":type(exc).__name__, "message":str(exc)[:300], "at":datetime.now(TAIPEI).isoformat()})
                            print(f"❌ GROUND_TRUTH CUTOFF ERROR | {type(exc).__name__} | {str(exc)[:300]}", flush=True)
                    if not gt_done:
                        self._finalize_unavailable_prediction_validations(trade_date)
                    if not gt_done and not self._gt_cutoff_recorded:
                        self.ledger.append_daily_event(trade_date, {
                            "event_type": "GROUND_TRUTH_CUTOFF_UNAVAILABLE",
                            "cutoff": "13:35",
                            "at": datetime.now(TAIPEI).isoformat(),
                        })
                        self._gt_cutoff_recorded = True
                    self.recovery.mark_clean_shutdown()
                    self.recovery_ledger.append(trade_date, {"event_type":"CLEAN_SHUTDOWN", "at":datetime.now(TAIPEI).isoformat()})
                    return 0
                time.sleep(MIS_INTERVAL_SECONDS)
        except KeyboardInterrupt:
            if manual_monitor:
                self.recovery.mark_clean_shutdown()
                self.recovery_ledger.append(trade_date, {
                    "event_type": "MANUAL_MONITOR_STOPPED",
                    "at": datetime.now(TAIPEI).isoformat(),
                })
                print("\n🛑 MANUAL MONITOR STOPPED | 已安全停止測試監控", flush=True)
                return 0
            raise
        finally:
            self.process_lock.release()


def main(argv=None):
    ap = argparse.ArgumentParser(description="天機 3K Production Runner")
    ap.add_argument("--once", action="store_true", help="重新建立盤前觀察池")
    ap.add_argument("--intraday-once", action="store_true", help="只執行一次 MIS Radar")
    ap.add_argument("--ground-truth-once", action="store_true", help="只執行一次收盤驗證")
    ap.add_argument("--run", action="store_true", help="完整交易日循環")
    ap.add_argument("--manual-monitor", action="store_true", help="手動持續盤中監控模式：忽略非盤中時間限制，持續 MIS Radar，供本地/線上測試")
    ap.add_argument("--recovery-status", action="store_true", help="顯示最近一次 runtime checkpoint")
    ap.add_argument("--simulate", type=Path, help="離線重播 MIS snapshot JSON/JSONL")
    ap.add_argument("--preflight", action="store_true", help="檢查 Production 環境與必要設定")
    ap.add_argument("--breakout-level", type=float, help="--simulate 使用的突破價位")
    ap.add_argument("--no-telegram", action="store_true")
    ap.add_argument("--repo-root")
    a = ap.parse_args(argv)
    r = TianjiProductionRunner(
        Path(a.repo_root).resolve() if a.repo_root else None,
        telegram=not a.no_telegram,
    )
    if a.preflight:
        from .tools.preflight import run_preflight
        result = run_preflight(Path(a.repo_root).resolve() if a.repo_root else None)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("ok") else 2
    if a.recovery_status:
        print(json.dumps(r.recovery.status(), ensure_ascii=False, indent=2))
    elif a.simulate:
        if a.breakout_level is None:
            ap.error("--simulate 必須搭配 --breakout-level")
        rows = IntradaySimulator.load(a.simulate)
        sim = IntradaySimulator({str(rows[0]["symbol"]): a.breakout_level} if rows else {}, BREAKOUT_BUFFER_PCT)
        result = sim.run(rows)
        print(json.dumps({"processed":result.processed,"triggers":result.triggers,"reasons":result.reasons,"states":result.states}, ensure_ascii=False, indent=2))
    elif a.intraday_once:
        r._load_pool()
        print(f"RADAR snapshots={r.poll_once()}")
    elif a.ground_truth_once:
        r._load_pool()
        print(f"GROUND_TRUTH rows={len(r.ground_truth())}")
    elif a.run or a.manual_monitor:
        # Local interactive `--run` is intentionally test-friendly outside the
        # Taiwan trading session: enter the same continuous Radar path instead
        # of exiting immediately. CI/online non-interactive `--run` keeps the
        # strict Production lifecycle and will still stop outside session.
        manual = bool(a.manual_monitor)
        if a.run and not manual and sys.stdin.isatty():
            phase = r.session.phase(datetime.now(TAIPEI))
            if phase in {"CLOSED", "PREMARKET_WAIT", "PREMARKET", "GROUND_TRUTH", "STOP"} and phase != "RADAR":
                manual = True
                print("🧪 LOCAL INTERACTIVE TEST | --run 在非盤中時間自動切換 MANUAL MONITOR", flush=True)
                print("   若要嚴格 Production lifecycle，請在線上/非互動環境執行 --run。", flush=True)
        r.run_forever(manual_monitor=manual)
    else:
        r.build_premarket_pool()
        print(f"PREMARKET_WATCHLIST size={len(r.pool)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
