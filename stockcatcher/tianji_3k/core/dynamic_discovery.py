from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time as dtime, timedelta
from typing import Any


@dataclass(frozen=True)
class DynamicDiscoveryConfig:
    """Intraday discovery rules; deliberately separate from 3K Core."""

    min_up_pct: float = 3.0
    min_yesterday_volume_lots: float = 1000.0
    min_current_volume_lots: float = 300.0
    min_volume_pace_ratio: float = 0.80
    max_history_enrich_per_cycle: int = 3
    max_history_attempts: int = 3


def _elapsed_fraction(now: datetime) -> float:
    """Fraction of the regular 09:00-13:30 session elapsed, bounded."""
    start = now.replace(hour=9, minute=0, second=0, microsecond=0)
    end = now.replace(hour=13, minute=30, second=0, microsecond=0)
    if now <= start:
        return 1.0 / 270.0
    if now >= end:
        return 1.0
    return max((now - start).total_seconds() / (4.5 * 3600), 1.0 / 270.0)


def discovery_candidates(
    raw: dict[str, dict[str, Any]],
    universe: dict[str, dict[str, Any]],
    *,
    existing: set[str] | None = None,
    attempts: dict[str, int] | None = None,
    now: datetime | None = None,
    config: DynamicDiscoveryConfig | None = None,
) -> list[dict[str, Any]]:
    """Cheap market-wide MIS gate. No FinMind/Fugle calls are made here.

    The gate intentionally finds *potential* intraday 3K candidates. It does
    not claim Stage 0-3 PASS and does not alter the premarket 3K Core.
    """
    cfg = config or DynamicDiscoveryConfig()
    existing = existing or set()
    attempts = attempts or {}
    now = now or datetime.now()
    fraction = _elapsed_fraction(now)
    out: list[dict[str, Any]] = []

    for sid, row in raw.items():
        sid = str(sid)
        if sid in existing or attempts.get(sid, 0) >= cfg.max_history_attempts:
            continue
        u = universe.get(sid, {})
        try:
            prev_vol = float(u.get("previous_volume_lots") or 0)
            up = float(row.get("up_pct") or 0)
            price = float(row.get("current_price") or 0)
            open_price = float(row.get("today_open") or 0)
            current_lots = float(row.get("cumulative_volume") or 0) / 1000.0
        except (TypeError, ValueError):
            continue

        if prev_vol < cfg.min_yesterday_volume_lots:
            continue
        if up < cfg.min_up_pct or price <= open_price:
            continue
        if current_lots < cfg.min_current_volume_lots:
            continue

        # Normalize today's cumulative volume by the portion of the session
        # already elapsed.  1.0 means today's pace is tracking yesterday's
        # full-day volume; 0.8 keeps discovery sensitive without overfitting.
        pace = (current_lots / prev_vol) / fraction if prev_vol > 0 else 0.0
        if pace < cfg.min_volume_pace_ratio:
            continue

        out.append({
            "symbol": sid,
            "name": u.get("name", ""),
            "market": u.get("market", ""),
            "up_pct": up,
            "current_price": price,
            "today_open": open_price,
            "current_volume_lots": current_lots,
            "previous_volume_lots": prev_vol,
            "volume_pace_ratio": pace,
            "discovery_source": "MIS_MARKET_WIDE",
        })

    # Momentum first, then abnormal volume pace. This makes the limited
    # historical-enrichment budget go to the strongest live candidates.
    out.sort(key=lambda x: (x["up_pct"], x["volume_pace_ratio"]), reverse=True)
    return out
