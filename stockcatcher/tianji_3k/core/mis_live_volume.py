"""Low-cost MIS live-volume pace estimator; never performs network requests."""
from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

TAIPEI = timezone(timedelta(hours=8))


class MISLiveVolumeEstimator:
    """Estimate live volume pace from successive MIS cumulative-volume snapshots.

    Baseline is the already-available 5-day average daily volume divided by 54
    five-minute bars in the 09:00-13:30 regular session. This is intentionally
    a lightweight fallback, not a same-time historical baseline.
    """

    def __init__(self, window_size: int = 8, min_window_seconds: float = 45.0,
                 max_window_seconds: float = 240.0, min_ratio: float = 1.5,
                 min_delta_lots: float = 2.0):
        self.window_size = max(3, int(window_size))
        self.min_window_seconds = float(min_window_seconds)
        self.max_window_seconds = float(max_window_seconds)
        self.min_ratio = float(min_ratio)
        self.min_delta_lots = float(min_delta_lots)
        self._history: dict[str, deque] = defaultdict(lambda: deque(maxlen=self.window_size))

    @staticmethod
    def _datetime(value) -> datetime:
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=TAIPEI)
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=TAIPEI)

    def observe(self, symbol: str, observed_at, cumulative_volume_lots: float,
                vma5_lots: float) -> dict:
        """Record one valid MIS snapshot and return a volume-pace assessment."""
        sid = str(symbol)
        now = self._datetime(observed_at)
        volume = float(cumulative_volume_lots)
        baseline_daily = float(vma5_lots or 0.0)
        history = self._history[sid]

        duplicate_observation = False
        if history:
            previous = history[-1]
            elapsed_from_previous = (now - previous[0]).total_seconds()
            # The runner warms the estimator before state evaluation, then the
            # same snapshot may be assessed again when a breakout is detected.
            # An identical timestamp+counter is idempotent, not a clock error.
            # A same-time counter change remains ambiguous and resets history.
            duplicate_observation = elapsed_from_previous == 0 and volume == previous[1]
            # Counter rollback, clock reversal, or a gap beyond the expanded
            # tolerance makes the local delta unreliable. Long-but-allowed
            # gaps are normalized by their actual elapsed seconds below.
            if (
                (elapsed_from_previous < 0)
                or (elapsed_from_previous == 0 and not duplicate_observation)
                or elapsed_from_previous > self.max_window_seconds
                or volume < previous[1]
            ):
                history.clear()

        if not history or now > history[-1][0]:
            history.append((now, volume))

        result = {
            "ready": False,
            "pass": False,
            "reason": "INSUFFICIENT_WINDOW",
            "window_seconds": 0.0,
            "volume_delta_lots": 0.0,
            "expected_volume_lots": 0.0,
            "live_volume_ratio": None,
            "baseline_5m_lots": baseline_daily / 54.0 if baseline_daily > 0 else None,
            "baseline_source": "VMA5_DAILY_DIV_54",
            "required_ratio": self.min_ratio,
            "max_window_seconds": self.max_window_seconds,
            "last_snapshot_gap_seconds": None,
        }
        if baseline_daily <= 0:
            result["reason"] = "NO_VALID_BASELINE_OR_HISTORY"
            return result
        if len(history) < 2:
            result["reason"] = "INSUFFICIENT_WINDOW"
            return result
        result["last_snapshot_gap_seconds"] = round(
            (history[-1][0] - history[-2][0]).total_seconds(), 2
        )

        # Choose the newest reference snapshot old enough to produce a stable
        # rate estimate. The 45-240s range tolerates slow Radar cycles while
        # normalizing expected volume by the actual elapsed time.
        reference = None
        elapsed = 0.0
        for candidate in reversed(list(history)[:-1]):
            candidate_elapsed = (now - candidate[0]).total_seconds()
            if self.min_window_seconds <= candidate_elapsed <= self.max_window_seconds:
                reference = candidate
                elapsed = candidate_elapsed
                break
        if reference is None:
            result["reason"] = "INSUFFICIENT_WINDOW"
            return result

        delta = max(0.0, volume - reference[1])
        baseline_5m = baseline_daily / 54.0
        expected = baseline_5m * elapsed / 300.0
        ratio = delta / expected if expected > 0 else None
        passed = bool(ratio is not None and ratio >= self.min_ratio and delta >= self.min_delta_lots)
        result.update({
            "ready": True,
            "pass": passed,
            "reason": "VOLUME_PACE_PASS" if passed else "VOLUME_PACE_BELOW_THRESHOLD",
            "window_seconds": round(elapsed, 2),
            "volume_delta_lots": round(delta, 3),
            "expected_volume_lots": round(expected, 3),
            "live_volume_ratio": round(ratio, 3) if ratio is not None else None,
        })
        return result
