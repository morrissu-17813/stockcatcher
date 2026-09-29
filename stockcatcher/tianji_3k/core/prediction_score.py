from __future__ import annotations

from dataclasses import dataclass, asdict


@dataclass(frozen=True)
class PredictionScore:
    """Explainable intraday 3K score; not a probability."""
    total: int
    trend: int
    breakout: int
    volume: int
    price: int
    components: dict

    def to_dict(self) -> dict:
        return asdict(self)


class IntradayPredictionScorer:
    """Score only observable, already-validated 3K components.

    100 points total:
      trend    30
      breakout 30
      volume   30
      price    10

    The score is intentionally not mapped to a success probability until
    historical Ground Truth calibration exists.
    """

    @staticmethod
    def _clamp(value: float, low: float, high: float) -> float:
        return max(low, min(high, value))

    def score(self, *, context: dict, current_price: float, up_pct: float,
              projected_ratio: float | None, effective_breakout: bool,
              confirmed_snapshots: int = 2) -> PredictionScore:
        ma20 = float(context.get("ma20") or 0)
        ma60 = float(context.get("ma60") or 0)
        ma20_prev = float(context.get("ma20_prev") or 0)
        prev_close = float(context.get("previous_close") or 0)
        breakout_level = float(context.get("breakout_level") or 0)

        # Trend: reward the actual Stage-1 structure, with a small slope bonus.
        trend = 0
        if ma20 > ma60 > 0:
            trend += 20
        if ma20 > ma20_prev > 0:
            trend += 10

        # Breakout: only an effective breakout gets the base points.
        breakout = 0
        if effective_breakout and breakout_level > 0:
            breakout = 20
            if confirmed_snapshots >= 2:
                breakout += 10

        # Volume: 30 points at projected ratio 2.0x or above, linear from 1.5x.
        volume = 0
        if projected_ratio is not None:
            volume = round(self._clamp((projected_ratio - 1.0) / 1.0 * 30, 0, 30))

        # Price: 5 points for >=4%, 5 points for price above previous close.
        price = 0
        if up_pct >= 4.0:
            price += 5
        if prev_close > 0 and current_price > prev_close:
            price += 5

        total = int(self._clamp(trend + breakout + volume + price, 0, 100))
        components = {
            "trend": {"ma20_gt_ma60": ma20 > ma60 > 0, "ma20_slope_up": ma20 > ma20_prev > 0},
            "breakout": {"effective": bool(effective_breakout), "confirmed_snapshots": int(confirmed_snapshots)},
            "volume": {"projected_ratio": projected_ratio, "threshold_ratio": 1.5},
            "price": {"up_pct": float(up_pct), "threshold_pct": 4.0},
        }
        return PredictionScore(total, trend, breakout, volume, price, components)
