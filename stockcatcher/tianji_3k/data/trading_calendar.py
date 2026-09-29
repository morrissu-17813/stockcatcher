from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd

from .config import FINMIND_TOKEN
from .finmind_budget import FinMindRequestBudget

LOG = logging.getLogger("tianji_3k.trading_calendar")
TAIPEI = timezone(timedelta(hours=8))
CALENDAR_DATASET = "TaiwanStockTradingDate"
CALENDAR_PUBLISH_TIME = time(18, 0)


@dataclass(frozen=True)
class CalendarSnapshot:
    source: str
    fetched_at: str
    rows: int
    min_date: str | None
    max_date: str | None


class TaiwanTradingCalendar:
    """Authoritative Taiwan equity trading-day calendar.

    The calendar is the upstream source for all historical-date requirements.
    FinMind exposes TaiwanStockTradingDate as the trading-day list; this class
    caches that list locally and never falls back to weekday/bdate_range logic
    for a required trading-day decision.
    """

    def __init__(self, token: str | None = None, cache_path: str | Path | None = None, budget: FinMindRequestBudget | None = None):
        self.token = (token if token is not None else FINMIND_TOKEN).strip()
        self.budget = budget or FinMindRequestBudget(limit=580)
        self.cache_path = Path(cache_path) if cache_path else (
            Path(__file__).resolve().parents[1] / "cache" / "reference" / "trading_calendar.json"
        )
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self._dates: set[date] = set()
        self._loaded = False
        self.last_snapshot: CalendarSnapshot | None = None

    def _load_local(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if not self.cache_path.exists():
            return
        try:
            payload = json.loads(self.cache_path.read_text(encoding="utf-8"))
            dates = payload.get("dates", []) if isinstance(payload, dict) else []
            self._dates = {pd.Timestamp(x).date() for x in dates}
            snap = payload.get("snapshot", {}) if isinstance(payload, dict) else {}
            if snap:
                self.last_snapshot = CalendarSnapshot(
                    source=str(snap.get("source", "cache")),
                    fetched_at=str(snap.get("fetched_at", "")),
                    rows=int(snap.get("rows", len(self._dates))),
                    min_date=snap.get("min_date"),
                    max_date=snap.get("max_date"),
                )
        except Exception as exc:
            LOG.warning("TRADING_CALENDAR_CACHE_INVALID path=%s error=%s", self.cache_path, type(exc).__name__)
            self._dates = set()

    def _fetch_remote(self) -> set[date]:
        if not self.token:
            raise RuntimeError("FINMIND_TOKEN is required for Trading Calendar bootstrap")
        from FinMind.data import DataLoader

        self.budget.reserve(reason="trading_calendar")
        dl = DataLoader()
        dl.login_by_token(self.token)
        try:
            df = dl.taiwan_stock_trading_date()
            self.budget.record_success()
        except Exception as exc:
            msg = str(exc).lower()
            self.budget.record_failure(quota=("402" in msg or "quota" in msg or "upper limit" in msg))
            raise
        if df is None or df.empty or "date" not in df.columns:
            raise RuntimeError("FinMind TaiwanStockTradingDate returned no dates")
        parsed = pd.to_datetime(df["date"], errors="coerce").dt.date.dropna()
        dates = set(parsed.tolist())
        if not dates:
            raise RuntimeError("Trading Calendar contains no valid dates")
        return dates

    def refresh(self, force: bool = False) -> CalendarSnapshot:
        self._load_local()
        if self._dates and not force:
            return self.last_snapshot or self._snapshot("cache")
        remote = self._fetch_remote()
        self._dates = remote
        return self._persist("finmind")

    def _persist(self, source: str) -> CalendarSnapshot:
        ordered = sorted(self._dates)
        now = datetime.now(TAIPEI).isoformat()
        snap = CalendarSnapshot(
            source=source,
            fetched_at=now,
            rows=len(ordered),
            min_date=ordered[0].isoformat() if ordered else None,
            max_date=ordered[-1].isoformat() if ordered else None,
        )
        tmp = self.cache_path.with_suffix(self.cache_path.suffix + ".tmp")
        tmp.write_text(
            json.dumps({"schema_version": "trading-calendar-v1", "dates": [x.isoformat() for x in ordered], "snapshot": snap.__dict__}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(self.cache_path)
        self.last_snapshot = snap
        return snap

    def _snapshot(self, source: str) -> CalendarSnapshot:
        ordered = sorted(self._dates)
        return CalendarSnapshot(
            source=source,
            fetched_at=datetime.now(TAIPEI).isoformat(),
            rows=len(ordered),
            min_date=ordered[0].isoformat() if ordered else None,
            max_date=ordered[-1].isoformat() if ordered else None,
        )

    def ensure(self) -> CalendarSnapshot:
        return self.refresh(force=False)

    def is_trading_day(self, value: str | date) -> bool:
        self.ensure()
        d = pd.Timestamp(value).date()
        return d in self._dates

    def expected_trading_days(self, start: str | date, end: str | date) -> list[date]:
        self.ensure()
        s, e = pd.Timestamp(start).date(), pd.Timestamp(end).date()
        if s > e:
            raise ValueError(f"invalid calendar range: {start} > {end}")
        result = sorted(d for d in self._dates if s <= d <= e)
        if not result:
            raise RuntimeError(f"Trading Calendar has no dates in range {s}..{e}")
        return result

    def previous_trading_days(self, end: str | date, count: int, include_end: bool = True) -> list[date]:
        if count <= 0:
            return []
        self.ensure()
        e = pd.Timestamp(end).date()
        dates = sorted((d for d in self._dates if d <= e and (include_end or d < e)), reverse=True)
        if len(dates) < count:
            raise RuntimeError(f"Trading Calendar history insufficient: need={count}, available={len(dates)}")
        return list(reversed(dates[:count]))

    def latest_completed(self, now: datetime | None = None) -> str:
        now = now or datetime.now(TAIPEI)
        self.ensure()
        eligible = [d for d in self._dates if d < now.date()]
        # The current trading day is not considered a completed daily K before
        # the vendor's normal post-close calendar publication window.
        if now.time() >= CALENDAR_PUBLISH_TIME and now.date() in self._dates:
            eligible.append(now.date())
        if not eligible:
            raise RuntimeError("Trading Calendar has no completed trading day")
        return max(eligible).isoformat()

    def validate_required_dates(self, required: Iterable[str | date], available: Iterable[str | date]) -> list[str]:
        required_set = {pd.Timestamp(x).date() for x in required}
        available_set = {pd.Timestamp(x).date() for x in available}
        return [d.isoformat() for d in sorted(required_set - available_set)]
