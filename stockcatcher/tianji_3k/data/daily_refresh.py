from __future__ import annotations

import json
import logging
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Iterable

import pandas as pd

from .cache_first import CacheFirstDailyProvider
from .config import FINMIND_TOKEN
from .data_integrity import validate_ohlc_frame, validate_required_history
from .trading_calendar import TaiwanTradingCalendar
from .finmind_budget import FinMindRequestBudget, FinMindBudgetExceeded, FinMindCircuitOpen
from .official_daily import OfficialDailySnapshotProvider

LOG = logging.getLogger("tianji_3k.daily_refresh")
TAIPEI = timezone(timedelta(hours=8))


@dataclass
class FreshnessResult:
    trade_date: str
    latest_completed_date: str
    cache_latest_before: str | None
    cache_latest_after: str | None
    symbols_requested: int
    symbols_refreshed: int
    symbols_failed: int
    rows_fetched: int
    status: str
    reason: str = ""
    calendar_rows: int = 0
    history_repairs: int = 0
    history_failures: int = 0


class LatestCompletedTradingDayResolver:
    """Resolve the latest completed daily bar from the Trading Calendar."""

    def __init__(self, token: str | None = None, calendar: TaiwanTradingCalendar | None = None):
        self.token = (token if token is not None else FINMIND_TOKEN).strip()
        self.calendar = calendar or TaiwanTradingCalendar(self.token)

    def resolve(self, now: datetime | None = None) -> str:
        return self.calendar.latest_completed(now)


class DailyDataRefreshManager:
    """Production daily-data coordinator.

    Trading Calendar is upstream of all date decisions. Existing cache is
    incrementally refreshed, and requested history is automatically repaired
    before Stage 1/2/3 are allowed to consume it.
    """

    def __init__(self, cache_dir: str | Path, audit_path: str | Path, token: str | None = None, budget: FinMindRequestBudget | None = None):
        self.cache_dir = Path(cache_dir)
        self.budget = budget or FinMindRequestBudget(limit=580)
        self.audit_path = Path(audit_path)
        self.calendar = TaiwanTradingCalendar(
            token or FINMIND_TOKEN,
            self.cache_dir.parent / "reference" / "trading_calendar.json",
            self.budget,
        )
        self.provider = CacheFirstDailyProvider(token or FINMIND_TOKEN, self.cache_dir, self.calendar, self.budget)
        self.resolver = LatestCompletedTradingDayResolver(token or FINMIND_TOKEN, self.calendar)
        self.official_daily = OfficialDailySnapshotProvider()

    def _cache_symbols(self) -> list[str]:
        symbols: set[str] = set()
        for path in self.cache_dir.glob("TaiwanStockPrice_*_*.json"):
            parts = path.stem.split("_")
            if len(parts) >= 3 and parts[0] == "TaiwanStockPrice" and parts[1].isdigit() and len(parts[1]) == 4:
                symbols.add(parts[1])
        return sorted(symbols)

    def _latest_cache_date(self) -> str | None:
        latest = None
        for path in self.cache_dir.glob("*.json"):
            try:
                raw = json.loads(path.read_text(encoding="utf-8-sig"))
                rows = raw if isinstance(raw, list) else raw.get("data", []) if isinstance(raw, dict) else []
                for row in rows:
                    if isinstance(row, dict) and row.get("date"):
                        d = pd.Timestamp(row["date"]).date()
                        latest = d if latest is None or d > latest else latest
            except Exception:
                continue
        return latest.isoformat() if latest else None

    def refresh_official_daily(self, target_date: str, symbols: Iterable[str] | None = None) -> dict:
        """Populate the local daily cache from one TWSE + one TPEx snapshot.

        Existing dates are merged idempotently. No FinMind request is used by
        this operation. A symbol allow-list can be supplied to limit writes.
        """
        result, frame = self.official_daily.fetch_result(target_date)
        if result.status != "READY":
            return {"status": result.status, "target_date": target_date,
                    "twse_rows": 0, "tpex_rows": 0, "rows_written": 0,
                    "errors": result.errors}
        allowed = None if symbols is None else {str(x) for x in symbols}
        written = 0
        for sid, grp in frame.groupby("stock_id"):
            sid = str(sid)
            if allowed is not None and sid not in allowed:
                continue
            try:
                self.provider._write_merged_cache(sid, grp.copy())
                written += 1
            except Exception as exc:
                LOG.warning("OFFICIAL_DAILY_CACHE_WRITE_FAILED symbol=%s error=%s", sid, exc)
        LOG.info("OFFICIAL_DAILY_READY date=%s twse=%d tpex=%d symbols=%d",
                 target_date, result.twse_rows, result.tpex_rows, written)
        return {"status": "READY", "target_date": target_date,
                "twse_rows": result.twse_rows, "tpex_rows": result.tpex_rows,
                "rows_written": written, "errors": []}

    def ensure_history(self, symbols: Iterable[str], end_date: str, bars: int) -> dict:
        """Ensure each symbol has the latest N valid trading-day bars.

        V1.2.2 request policy:
        - the shared Trading Calendar is already bootstrapped once per FULL_SCAN;
        - each symbol gets at most ONE FinMind Daily request in this call;
        - budget exhaustion is recorded as ``budget_blocked`` rather than
          pretending the symbol simply has missing history.
        """
        required = self.calendar.previous_trading_days(end_date, bars, include_end=True)
        start_date = required[0].isoformat()
        result = {
            "requested": 0,
            "cache_ready": 0,
            "repair_attempted": 0,
            "repaired": 0,
            "failed": 0,
            "budget_blocked": 0,
            "rows": 0,
            "errors": [],
        }
        for sid in sorted(set(str(x) for x in symbols)):
            result["requested"] += 1
            try:
                df = self.provider.get_daily(sid, start_date, end_date)
                integrity = validate_ohlc_frame(df)
                if not integrity.ok:
                    raise RuntimeError(integrity.reason)
                check = validate_required_history(df.to_dict("records"), self.calendar, end_date, bars)
                if not check.ok:
                    raise RuntimeError(check.reason + (":" + ",".join(check.missing_dates) if check.missing_dates else ""))
                result["rows"] += len(df)
                if self.provider.last_source == "cache":
                    result["cache_ready"] += 1
                else:
                    result["repair_attempted"] += 1
                    result["repaired"] += 1
            except (FinMindBudgetExceeded, FinMindCircuitOpen) as exc:
                result["budget_blocked"] += 1
                result["errors"].append({
                    "symbol": sid,
                    "error_type": type(exc).__name__,
                    "reason": str(exc)[:300],
                })
                LOG.warning("HISTORY_BUDGET_BLOCKED symbol=%s end=%s error=%s", sid, end_date, type(exc).__name__)
            except Exception as exc:
                result["failed"] += 1
                result["errors"].append({
                    "symbol": sid,
                    "error_type": type(exc).__name__,
                    "reason": str(exc)[:300],
                })
                LOG.warning("HISTORY_REPAIR_FAILED symbol=%s end=%s error=%s", sid, end_date, type(exc).__name__)
        return result

    def bootstrap(self, trade_date: str) -> FreshnessResult:
        """Bootstrap shared daily context without refreshing every cached symbol.

        The old implementation walked every cached symbol before Stage 0. With
        hundreds of symbols this could consume hundreds of FinMind requests
        before the 3K history repair even started. V1.2.2 makes the calendar the
        single upstream bootstrap and defers symbol-level refresh to the actual
        Stage 0 candidate set.
        """
        calendar_snapshot = self.calendar.refresh(force=True)
        latest_completed = self.resolver.resolve()
        if latest_completed > trade_date:
            latest_completed = trade_date
        before = self._latest_cache_date()
        result = FreshnessResult(
            trade_date=trade_date,
            latest_completed_date=latest_completed,
            cache_latest_before=before,
            cache_latest_after=before,
            symbols_requested=0,
            symbols_refreshed=0,
            symbols_failed=0,
            rows_fetched=0,
            status="READY",
            reason="calendar_bootstrapped; symbol refresh deferred until Stage 0 candidates",
            calendar_rows=calendar_snapshot.rows,
        )
        self._write_audit(result)
        return result

    def refresh_symbols(self, symbols: Iterable[str], target_date: str, max_requests: int | None = None) -> dict:
        """Refresh only the supplied symbols to the completed daily-bar date.

        ``max_requests`` is a hard orchestration guard. Cache hits do not
        consume it; only actual FinMind fallbacks count against the limit.
        """
        requested = sorted(set(str(x) for x in symbols))
        refreshed = failed = rows = 0
        budget_blocked = 0
        attempted = 0
        errors = []
        for sid in requested:
            try:
                before = self.budget.snapshot()["used"]
                if max_requests is not None and attempted >= max_requests:
                    budget_blocked += 1
                    errors.append({"symbol": sid, "error_type": "REQUEST_PLAN_BLOCKED", "reason": f"max_requests={max_requests}"})
                    LOG.warning("DAILY_REFRESH_PLAN_BLOCKED symbol=%s target=%s max_requests=%s", sid, target_date, max_requests)
                    continue
                df = self.provider.get_daily(sid, target_date, target_date)
                after = self.budget.snapshot()["used"]
                attempted += max(0, after - before)
                refreshed += 1
                rows += len(df)
            except (FinMindBudgetExceeded, FinMindCircuitOpen) as exc:
                attempted += 1
                budget_blocked += 1
                failed += 1
                errors.append({"symbol": sid, "error_type": type(exc).__name__, "reason": str(exc)[:300]})
                LOG.warning("DAILY_REFRESH_BUDGET_BLOCKED symbol=%s target=%s error=%s", sid, target_date, type(exc).__name__)
            except Exception as exc:
                failed += 1
                errors.append({"symbol": sid, "error_type": type(exc).__name__, "reason": str(exc)[:300]})
                LOG.warning("DAILY_REFRESH_FAILED symbol=%s target=%s error=%s", sid, target_date, type(exc).__name__)
        return {
            "requested": len(requested),
            "refreshed": refreshed,
            "failed": failed,
            "budget_blocked": budget_blocked,
            "requests_attempted": attempted,
            "rows": rows,
            "errors": errors,
            "budget": self.budget.snapshot(),
        }

    def refresh(self, trade_date: str, symbols: Iterable[str] | None = None) -> FreshnessResult:
        """Backward-compatible API.

        Unlike V1.2.1, ``symbols=None`` no longer means 'refresh every cache
        symbol'. It performs the safe calendar bootstrap only. Pass an explicit
        symbol list when symbol-level refresh is actually required.
        """
        result = self.bootstrap(trade_date)
        if symbols:
            stats = self.refresh_symbols(symbols, result.latest_completed_date)
            result.symbols_requested = stats["requested"]
            result.symbols_refreshed = stats["refreshed"]
            result.symbols_failed = stats["failed"]
            result.rows_fetched = stats["rows"]
            result.cache_latest_after = self._latest_cache_date()
            result.status = "OK" if stats["failed"] == 0 else "PARTIAL"
            result.reason = "" if result.status == "OK" else "symbol refresh partial"
            self._write_audit(result)
        return result

    def record_history_repair(self, result: dict) -> None:
        """Persist history-repair statistics into the freshness manifest."""
        existing = {}
        if self.audit_path.exists():
            try:
                existing = json.loads(self.audit_path.read_text(encoding="utf-8"))
            except Exception:
                existing = {}
        failed = int(result.get("failed", 0))
        budget_blocked = int(result.get("budget_blocked", 0))
        existing["history_integrity"] = {
            "requested": int(result.get("requested", 0)),
            "cache_ready": int(result.get("cache_ready", 0)),
            "repair_attempted": int(result.get("repair_attempted", 0)),
            "repaired": int(result.get("repaired", 0)),
            "failed": failed,
            "budget_blocked": budget_blocked,
            "rows": int(result.get("rows", 0)),
            "status": "PASS" if failed == 0 and budget_blocked == 0 else ("BUDGET_BLOCKED" if budget_blocked else "PARTIAL"),
            "errors": result.get("errors", [])[:50],
        }
        tmp = self.audit_path.with_suffix(self.audit_path.suffix + ".tmp")
        tmp.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.audit_path)

    def _write_audit(self, result: FreshnessResult) -> None:
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        payload = asdict(result)
        payload["provider_stats"] = self.provider.stats()
        payload["finmind_budget"] = self.budget.snapshot()
        payload["calendar"] = asdict(self.calendar.last_snapshot) if self.calendar.last_snapshot else None
        tmp = self.audit_path.with_suffix(self.audit_path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.audit_path)
