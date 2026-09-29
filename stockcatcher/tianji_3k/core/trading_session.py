from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, datetime, timezone, timedelta

from ..data.trading_calendar import TaiwanTradingCalendar

TAIPEI = timezone(timedelta(hours=8))


@dataclass(frozen=True)
class SessionWindow:
    premarket_start: str = "08:20"
    market_start: str = "09:00"
    market_end: str = "13:30"
    shutdown: str = "13:35"


class TradingSession:
    """Operational session clock backed by TaiwanTradingCalendar.

    Historical/current trading-day decisions use the calendar. For a future
    date not yet published by the calendar provider, weekday + explicit
    TIANJI_HOLIDAYS is used only as a session-start safety fallback; historical
    data requirements never use that fallback.
    """

    def __init__(self, holidays: set[str] | None = None, calendar: TaiwanTradingCalendar | None = None):
        raw = os.getenv("TIANJI_HOLIDAYS", "")
        env_holidays = {x.strip() for x in raw.split(",") if x.strip()}
        self.holidays = set(holidays or set()) | env_holidays
        self.calendar = calendar or TaiwanTradingCalendar()
        self.window = SessionWindow()

    def is_trading_candidate(self, d: date) -> bool:
        if d.isoformat() in self.holidays or d.weekday() >= 5:
            return False
        try:
            self.calendar.ensure()
        except Exception:
            # Session gating must not make the process crash before data bootstrap.
            # Historical data fetching remains fail-closed and calendar-dependent.
            return True
        known_max = self.calendar.last_snapshot.max_date if self.calendar.last_snapshot else None
        if d.isoformat() <= str(known_max or ""):
            return self.calendar.is_trading_day(d)
        # Future dates may not yet be published by the daily trading-date feed.
        return True

    def phase(self, now: datetime | None = None) -> str:
        now = now or datetime.now(TAIPEI)
        if not self.is_trading_candidate(now.date()):
            return "CLOSED"
        hhmm = now.strftime("%H:%M")
        if hhmm < self.window.premarket_start:
            return "PREMARKET_WAIT"
        if hhmm < self.window.market_start:
            return "PREMARKET"
        if hhmm < self.window.market_end:
            return "RADAR"
        if hhmm < self.window.shutdown:
            return "GROUND_TRUTH"
        return "STOP"
