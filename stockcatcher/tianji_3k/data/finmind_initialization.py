from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Callable, Iterable

import pandas as pd

from .cache_first import CacheFirstDailyProvider
from .config import FINMIND_TOKEN
from .finmind_budget import FinMindBudgetExceeded, FinMindCircuitOpen, FinMindRequestBudget
from .stock_universe import StockUniverseProvider
from .trading_calendar import TaiwanTradingCalendar

LOG = logging.getLogger("tianji_3k.finmind_initialization")
TAIPEI = timezone(timedelta(hours=8))


@dataclass
class InitializationResult:
    status: str
    trade_date: str
    latest_completed_date: str
    start_date: str
    bars_required: int
    total_symbols: int
    completed_symbols: int
    pending_symbols: int
    requests_used: int
    checkpoint_path: str
    message: str = ""


class ProductionCacheInitializer:
    """Build a clean production daily-cache baseline with resumable FinMind I/O.

    Design goals:
      * one shared rolling 580-request safety budget;
      * at most one FinMind history request per symbol for the initialization pass;
      * cache-first, so already-complete symbols never consume a request;
      * durable checkpoint before/after every symbol;
      * budget exhaustion pauses without marking remaining symbols as failures;
      * restart resumes from the pending symbol list instead of starting over.
    """

    SCHEMA_VERSION = "production-cache-init-v1"

    def __init__(
        self,
        cache_dir: str | Path,
        checkpoint_path: str | Path,
        token: str | None = None,
        budget: FinMindRequestBudget | None = None,
        calendar: TaiwanTradingCalendar | None = None,
        provider: CacheFirstDailyProvider | None = None,
        universe_provider: StockUniverseProvider | None = None,
        sleep_fn: Callable[[float], None] = time.sleep,
        min_universe_symbols: int = 500,
    ):
        self.cache_dir = Path(cache_dir)
        self.checkpoint_path = Path(checkpoint_path)
        self.token = (token if token is not None else FINMIND_TOKEN).strip()
        self.budget = budget or FinMindRequestBudget(limit=580)
        self.calendar = calendar or TaiwanTradingCalendar(
            self.token,
            self.cache_dir.parent / "reference" / "trading_calendar.json",
            self.budget,
        )
        self.provider = provider or CacheFirstDailyProvider(
            self.token, self.cache_dir, self.calendar, self.budget
        )
        self.universe_provider = universe_provider or StockUniverseProvider()
        self.sleep_fn = sleep_fn
        self.min_universe_symbols = int(min_universe_symbols)

    def _write_checkpoint(self, payload: dict) -> None:
        import time as _time
        self.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        content = json.dumps(payload, ensure_ascii=False, indent=2)
        tmp = self.checkpoint_path.with_suffix(self.checkpoint_path.suffix + ".tmp")
        tmp.write_text(content, encoding="utf-8")
        last_error = None
        for attempt in range(5):
            try:
                tmp.replace(self.checkpoint_path)
                return
            except PermissionError as exc:
                last_error = exc
                if attempt < 4:
                    _time.sleep(0.25 * (attempt + 1))
        try:
            self.checkpoint_path.write_text(content, encoding="utf-8")
            tmp.unlink(missing_ok=True)
            return
        except Exception:
            tmp.unlink(missing_ok=True)
            if last_error is not None:
                raise last_error
            raise

    def load_checkpoint(self) -> dict | None:
        if not self.checkpoint_path.exists():
            return None
        try:
            data = json.loads(self.checkpoint_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else None
        except (OSError, ValueError, TypeError):
            LOG.warning("INIT_CHECKPOINT_INVALID path=%s", self.checkpoint_path)
            return None

    def _base_payload(
        self,
        *,
        trade_date: str,
        latest_completed_date: str,
        start_date: str,
        bars_required: int,
        symbols: list[str],
        completed: list[str],
        pending: list[str],
        status: str,
        message: str = "",
        current_symbol: str | None = None,
    ) -> dict:
        b = self.budget.snapshot()
        return {
            "schema_version": self.SCHEMA_VERSION,
            "status": status,
            "trade_date": trade_date,
            "latest_completed_date": latest_completed_date,
            "start_date": start_date,
            "bars_required": bars_required,
            "total_symbols": len(symbols),
            "completed_symbols": completed,
            "pending_symbols": pending,
            "current_symbol": current_symbol,
            "requests_used": b["used"],
            "budget": b,
            "updated_at": datetime.now(TAIPEI).isoformat(),
            "message": message,
        }

    def _discover_symbols(self) -> list[str]:
        rows = self.universe_provider.fetch()
        # The provider's listed/OTC endpoints are main-board common-stock feeds.
        # Keep only the explicit common-stock universe and 4-digit symbols.
        symbols = {
            str(row.get("symbol", "")).strip()
            for row in rows
            if str(row.get("security_type", "")).strip().lower() == "common_stock"
            and str(row.get("symbol", "")).strip().isdigit()
            and len(str(row.get("symbol", "")).strip()) == 4
        }
        # Never allow a transient universe API failure to look like a valid
        # empty/partial production baseline. The current Taiwan main-board
        # universe is comfortably above this conservative floor.
        if len(symbols) < self.min_universe_symbols:
            raise RuntimeError(f"UNIVERSE_DISCOVERY_INCOMPLETE: symbols={len(symbols)} minimum={self.min_universe_symbols}")
        return sorted(symbols)

    def _checkpoint_result(self, data: dict, message: str = "") -> InitializationResult:
        return InitializationResult(
            status=str(data.get("status", "UNKNOWN")),
            trade_date=str(data.get("trade_date", "")),
            latest_completed_date=str(data.get("latest_completed_date", "")),
            start_date=str(data.get("start_date", "")),
            bars_required=int(data.get("bars_required", 0)),
            total_symbols=int(data.get("total_symbols", 0)),
            completed_symbols=len(data.get("completed_symbols", [])),
            pending_symbols=len(data.get("pending_symbols", [])),
            requests_used=int(data.get("budget", {}).get("used", data.get("requests_used", 0))),
            checkpoint_path=str(self.checkpoint_path),
            message=message or str(data.get("message", "")),
        )

    def initialize(
        self,
        trade_date: str,
        *,
        bars_required: int = 61,
        resume: bool = True,
        wait_for_budget: bool = False,
        symbols: Iterable[str] | None = None,
    ) -> InitializationResult:
        """Run or resume the production-cache initialization pass.

        When ``wait_for_budget`` is False, hitting the 580 rolling limit returns
        ``PAUSED_BUDGET`` immediately after persisting a checkpoint. When True,
        the process sleeps until the earliest reservation expires and continues.
        """
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.calendar.refresh(force=not bool(self.calendar.last_snapshot))
        latest_completed = self.calendar.latest_completed()
        if latest_completed > trade_date:
            latest_completed = trade_date
        history_window = bars_required + max(20, bars_required // 3)
        required = self.calendar.previous_trading_days(latest_completed, history_window, include_end=True)
        start_date = required[0].isoformat()

        planned_symbols = sorted(set(str(x).strip() for x in symbols)) if symbols is not None else None
        if planned_symbols is not None and not planned_symbols:
            raise RuntimeError("INITIALIZATION_SYMBOL_PLAN_EMPTY")
        checkpoint = self.load_checkpoint() if resume else None
        symbols: list[str]
        completed: list[str]
        checkpoint_matches = (
            checkpoint
            and checkpoint.get("trade_date") == trade_date
            and checkpoint.get("latest_completed_date") == latest_completed
            and checkpoint.get("start_date") == start_date
            and (planned_symbols is None or sorted(set(str(x) for x in checkpoint.get("all_symbols", []))) == planned_symbols)
        )
        if checkpoint_matches:
            symbols = sorted(set(str(x) for x in checkpoint.get("all_symbols", [])))
            completed = sorted(set(str(x) for x in checkpoint.get("completed_symbols", [])))
            pending = [s for s in symbols if s not in set(completed)]
            LOG.info("INIT_RESUME trade_date=%s completed=%d pending=%d", trade_date, len(completed), len(pending))
        else:
            symbols = planned_symbols if planned_symbols is not None else self._discover_symbols()
            completed = []
            pending = list(symbols)
            self._write_checkpoint({
                **self._base_payload(
                    trade_date=trade_date,
                    latest_completed_date=latest_completed,
                    start_date=start_date,
                    bars_required=bars_required,
                    symbols=symbols,
                    completed=completed,
                    pending=pending,
                    status="RUNNING",
                ),
                "all_symbols": symbols,
            })

        completed_set = set(completed)
        pending = [s for s in symbols if s not in completed_set]

        for sid in pending:
            while True:
                # Check the budget before touching the provider. Cache hits do not
                # need a request and are therefore allowed even at the limit.
                try:
                    snapshot = self.budget.snapshot()
                    if snapshot["used"] >= snapshot["limit"]:
                        payload = {
                            **self._base_payload(
                                trade_date=trade_date,
                                latest_completed_date=latest_completed,
                                start_date=start_date,
                                bars_required=bars_required,
                                symbols=symbols,
                                completed=sorted(completed_set),
                                pending=[x for x in symbols if x not in completed_set],
                                status="PAUSED_BUDGET",
                                message="FinMind rolling safety budget reached; checkpoint saved before resume.",
                                current_symbol=sid,
                            ),
                            "all_symbols": symbols,
                        }
                        self._write_checkpoint(payload)
                        if not wait_for_budget:
                            return self._checkpoint_result(payload)
                        wait_seconds = self.budget.seconds_until_available()
                        LOG.warning("INIT_WAIT_FOR_BUDGET seconds=%.1f pending=%d", wait_seconds, len(payload["pending_symbols"]))
                        self.sleep_fn(max(0.0, wait_seconds))
                        continue  # retry the SAME symbol after capacity returns

                    # get_daily is cache-first. A complete cache row is a no-op;
                    # a missing 61-day range consumes exactly one FinMind request.
                    if isinstance(self.provider, CacheFirstDailyProvider):
                        df = self.provider.get_daily(
                            sid, start_date, latest_completed, allow_symbol_non_trading=True
                        )
                        frame = df if isinstance(df, pd.DataFrame) else pd.DataFrame(df)
                        valid_bars = int(len(frame.dropna(subset=["open", "high", "low", "close", "volume"])))
                        if valid_bars < bars_required:
                            raise RuntimeError(f"HISTORY_VALID_BARS_INSUFFICIENT:{valid_bars}<{bars_required}")
                    else:
                        # Keep provider/test-double compatibility for existing unit tests.
                        self.provider.get_daily(sid, start_date, latest_completed)
                    completed_set.add(sid)
                    payload = {
                        **self._base_payload(
                            trade_date=trade_date,
                            latest_completed_date=latest_completed,
                            start_date=start_date,
                            bars_required=bars_required,
                            symbols=symbols,
                            completed=sorted(completed_set),
                            pending=[x for x in symbols if x not in completed_set],
                            status="RUNNING",
                            current_symbol=None,
                        ),
                        "all_symbols": symbols,
                    }
                    self._write_checkpoint(payload)
                    break
                except (FinMindBudgetExceeded, FinMindCircuitOpen) as exc:
                    payload = {
                        **self._base_payload(
                            trade_date=trade_date,
                            latest_completed_date=latest_completed,
                            start_date=start_date,
                            bars_required=bars_required,
                            symbols=symbols,
                            completed=sorted(completed_set),
                            pending=[x for x in symbols if x not in completed_set],
                            status="PAUSED_BUDGET",
                            message=str(exc)[:300],
                            current_symbol=sid,
                        ),
                        "all_symbols": symbols,
                    }
                    self._write_checkpoint(payload)
                    if not wait_for_budget:
                        return self._checkpoint_result(payload)
                    wait_seconds = self.budget.seconds_until_available()
                    LOG.warning("INIT_WAIT_FOR_BUDGET seconds=%.1f pending=%d", wait_seconds, len(payload["pending_symbols"]))
                    self.sleep_fn(max(0.0, wait_seconds))
                    continue  # retry the SAME symbol after capacity returns
                except Exception as exc:
                    payload = {
                        **self._base_payload(
                            trade_date=trade_date,
                            latest_completed_date=latest_completed,
                            start_date=start_date,
                            bars_required=bars_required,
                            symbols=symbols,
                            completed=sorted(completed_set),
                            pending=[x for x in symbols if x not in completed_set],
                            status="PAUSED_ERROR",
                            message=f"{type(exc).__name__}: {exc}"[:500],
                            current_symbol=sid,
                        ),
                        "all_symbols": symbols,
                    }
                    self._write_checkpoint(payload)
                    raise

        payload = {
            **self._base_payload(
                trade_date=trade_date,
                latest_completed_date=latest_completed,
                start_date=start_date,
                bars_required=bars_required,
                symbols=symbols,
                completed=sorted(completed_set),
                pending=[],
                status="COMPLETE",
                message="Production daily cache initialization complete.",
            ),
            "all_symbols": symbols,
            "completed_at": datetime.now(TAIPEI).isoformat(),
        }
        self._write_checkpoint(payload)
        return self._checkpoint_result(payload)
