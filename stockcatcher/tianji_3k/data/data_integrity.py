from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Iterable

import pandas as pd

from .trading_calendar import TaiwanTradingCalendar


@dataclass(frozen=True)
class IntegrityResult:
    status: str
    reason: str = ""
    required_dates: tuple[str, ...] = ()
    missing_dates: tuple[str, ...] = ()
    duplicate_dates: tuple[str, ...] = ()
    invalid_rows: int = 0

    @property
    def ok(self) -> bool:
        return self.status == "PASS"


def validate_ohlc_frame(df: pd.DataFrame) -> IntegrityResult:
    if df is None or df.empty:
        return IntegrityResult("FAIL", "DATA_EMPTY")
    required = {"date", "open", "high", "low", "close", "volume"}
    if not required.issubset(df.columns):
        return IntegrityResult("FAIL", "DATA_SCHEMA_MISSING")
    x = df.copy()
    x["date"] = pd.to_datetime(x["date"], errors="coerce").dt.date
    numeric = ["open", "high", "low", "close", "volume"]
    for col in numeric:
        x[col] = pd.to_numeric(x[col], errors="coerce")
    duplicate_dates = tuple(sorted({d.isoformat() for d in x.loc[x["date"].duplicated(keep=False), "date"].dropna()}))
    invalid = (
        x["date"].isna()
        | x[numeric].isna().any(axis=1)
        | (x["volume"] < 0)
        | (x["high"] < x["low"])
        | (x["high"] < x["open"])
        | (x["high"] < x["close"])
        | (x["low"] > x["open"])
        | (x["low"] > x["close"])
    )
    if duplicate_dates:
        return IntegrityResult("FAIL", "DUPLICATE_DATE", duplicate_dates=duplicate_dates, invalid_rows=int(invalid.sum()))
    if invalid.any():
        return IntegrityResult("FAIL", "OHLC_INVALID", invalid_rows=int(invalid.sum()))
    return IntegrityResult("PASS")


def validate_required_history(
    bars: Iterable[dict[str, Any]],
    calendar: TaiwanTradingCalendar,
    end_date: str | date,
    count: int,
) -> IntegrityResult:
    expected = calendar.previous_trading_days(end_date, count, include_end=True)
    required = tuple(d.isoformat() for d in expected)
    available = {pd.Timestamp(r.get("date")).date() for r in bars if r.get("date")}
    missing = tuple(d.isoformat() for d in expected if d not in available)
    if missing:
        return IntegrityResult("FAIL", "HISTORY_MISSING", required, missing)
    return IntegrityResult("PASS", required_dates=required)


def validate_k012(
    bars: Iterable[dict[str, Any]], calendar: TaiwanTradingCalendar, latest_date: str
) -> IntegrityResult:
    rows = list(bars)
    required = calendar.previous_trading_days(latest_date, 3, include_end=True)
    required_dates = tuple(d.isoformat() for d in required)
    by_date = {pd.Timestamp(r.get("date")).date(): r for r in rows if r.get("date")}
    missing = tuple(d.isoformat() for d in required if d not in by_date)
    if missing:
        return IntegrityResult("FAIL", "K012_MISSING", required_dates, missing)
    if not (required[0] < required[1] < required[2]):
        return IntegrityResult("FAIL", "K012_DATE_ORDER", required_dates)
    return IntegrityResult("PASS", required_dates=required_dates)
