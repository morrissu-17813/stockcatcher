from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class DynamicCandidateResult:
    symbol: str
    eligible: bool
    reason: str
    context: dict[str, Any] | None = None


def evaluate_dynamic_history(symbol: str, frame: pd.DataFrame, *, name: str = "", market: str = "", trade_date: str = "") -> DynamicCandidateResult:
    """Evaluate only the historical 3K background needed by the intraday radar.

    This does not alter the existing Stage 0-3 production pipeline. It is a
    separate gate for a stock discovered intraday by the market-wide MIS scan.
    """
    if frame is None or frame.empty or len(frame) < 61:
        return DynamicCandidateResult(symbol, False, "HISTORY_INSUFFICIENT")

    x = frame.copy().sort_values("date").reset_index(drop=True)
    for col in ("open", "high", "low", "close", "volume"):
        x[col] = pd.to_numeric(x[col], errors="coerce")
    x = x.dropna(subset=["open", "high", "low", "close", "volume"])
    if len(x) < 61:
        return DynamicCandidateResult(symbol, False, "HISTORY_INVALID")

    k0, k1, k2 = x.iloc[-1], x.iloc[-2], x.iloc[-3]
    closes = x["close"]
    ma20 = float(closes.iloc[-20:].mean())
    ma60 = float(closes.iloc[-60:].mean())
    ma20_prev = float(closes.iloc[-21:-1].mean())

    # Preserve the production Stage-1 trend definition.
    if not (k0["close"] > ma20 and k0["close"] > ma60 and ma20 > ma60 and ma20 > ma20_prev):
        return DynamicCandidateResult(symbol, False, "STAGE1_TREND_FAIL")

    # T-day intraday potential: today's live price can still become the new K0.
    breakout_level = float(max(k0["high"], k1["high"]))
    vma5 = float(x["volume_lots"].iloc[-5:].mean()) if "volume_lots" in x else float((x["volume"].iloc[-5:] / 1000).mean())
    yesterday_volume_lots = float(k0["volume"] / 1000)
    if vma5 < 1000:
        return DynamicCandidateResult(symbol, False, "STAGE3_BASELINE_VMA5_LT_1000")

    context = {
        "trade_date": trade_date,
        "symbol": str(symbol),
        "name": name,
        "market": market,
        "industry": "",
        "source_data_date": str(k0["date"])[:10],
        "previous_close": float(k0["close"]),
        "k1_high": float(k0["high"]),
        "k2_high": float(k1["high"]),
        "breakout_level": breakout_level,
        "ma20": ma20,
        "ma60": ma60,
        "ma20_prev": ma20_prev,
        "vma5_lots": vma5,
        "yesterday_volume_lots": yesterday_volume_lots,
        # Dynamic Discovery is deliberately NOT a Stage 0-3 PASS.
        # These fields are explicit so downstream audit/validation cannot
        # accidentally treat a dynamic candidate as a premarket 3K PASS.
        "stage0_pass": False,
        "stage1_pass": True,
        "stage2_pass": False,
        "stage3_pass": False,
        "final_pool": False,
        "dynamic_candidate": True,
        "dynamic_discovery_pass": True,
        "dynamic_history_ready": True,
    }
    return DynamicCandidateResult(symbol, True, "DYNAMIC_3K_HISTORY_READY", context)
