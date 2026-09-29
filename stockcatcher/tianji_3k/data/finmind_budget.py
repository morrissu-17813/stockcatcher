from __future__ import annotations

import logging
import time
from collections import deque
from threading import Lock

log = logging.getLogger("tianji_3k.finmind_budget")


class FinMindBudgetExceeded(RuntimeError):
    """Raised when the Tianji rolling safety budget is exhausted."""


class FinMindCircuitOpen(RuntimeError):
    """Raised while the FinMind circuit breaker is open."""


class FinMindRequestBudget:
    """Shared rolling 60-minute FinMind request budget.

    Tianji deliberately stops at 580 requests in any rolling 60-minute
    window, reserving 20 requests below the documented 600/hour ceiling.
    Old reservations automatically expire after 60 minutes; no process
    restart or fixed-clock reset is required.
    """

    def __init__(self, limit: int = 580, window_seconds: int = 3600,
                 failure_threshold: int = 3, cooldown_seconds: int = 300):
        self.limit = int(limit)
        self.window_seconds = int(window_seconds)
        self.failure_threshold = int(failure_threshold)
        self.cooldown_seconds = int(cooldown_seconds)
        self._timestamps = deque()
        self._lock = Lock()
        self._consecutive_failures = 0
        self._circuit_open_until = 0.0
        self.total_reserved = 0
        self.total_blocked = 0
        self.total_failures = 0

    def _prune(self, now: float) -> None:
        cutoff = now - self.window_seconds
        while self._timestamps and self._timestamps[0] <= cutoff:
            self._timestamps.popleft()

    def reserve(self, reason: str = "") -> None:
        now = time.monotonic()
        with self._lock:
            self._prune(now)
            if now < self._circuit_open_until:
                self.total_blocked += 1
                raise FinMindCircuitOpen("FinMind circuit breaker is open")
            if len(self._timestamps) >= self.limit:
                self.total_blocked += 1
                log.error("FINMIND_BUDGET_EXCEEDED used=%d limit=%d reason=%s", len(self._timestamps), self.limit, reason)
                raise FinMindBudgetExceeded(f"FinMind rolling safety gate reached: {self.limit}")
            self._timestamps.append(now)
            self.total_reserved += 1

    def record_success(self) -> None:
        with self._lock:
            self._consecutive_failures = 0

    def record_failure(self, *, quota: bool = False) -> None:
        now = time.monotonic()
        with self._lock:
            self.total_failures += 1
            self._consecutive_failures += 1
            if quota or self._consecutive_failures >= self.failure_threshold:
                self._circuit_open_until = max(self._circuit_open_until, now + self.cooldown_seconds)
                log.error("FINMIND_CIRCUIT_OPEN failures=%d quota=%s", self._consecutive_failures, quota)

    def snapshot(self) -> dict:
        now = time.monotonic()
        with self._lock:
            self._prune(now)
            used = len(self._timestamps)
            return {
                "limit": self.limit,
                "window_seconds": self.window_seconds,
                "used": used,
                "remaining": max(0, self.limit - used),
                "total_reserved": self.total_reserved,
                "total_blocked": self.total_blocked,
                "total_failures": self.total_failures,
                "circuit_open": now < self._circuit_open_until,
            }


# Rolling-window helper used by resumable production initialization.
def _seconds_until_available(self) -> float:
    now = time.monotonic()
    with self._lock:
        self._prune(now)
        if not self._timestamps:
            return 0.0
        return max(0.0, self._timestamps[0] + self.window_seconds - now)

FinMindRequestBudget.seconds_until_available = _seconds_until_available
