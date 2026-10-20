"""Auditable post-signal validation using completed daily candles only.

This module does not place orders or mutate Tianji 3K production records.
"""
from __future__ import annotations
from datetime import date
from typing import Any


def validate_signal_daily(symbol: str, signal_date: str, signal_price: float,
                          candles: list[dict[str, Any]], horizon_days: int = 7,
                          stop_loss_pct: float = 2.0) -> dict[str, Any]:
    try:
        signal_day = date.fromisoformat(str(signal_date)[:10])
        ref_price = float(signal_price)
    except (TypeError, ValueError):
        raise ValueError("signal_date 必須為 YYYY-MM-DD，signal_price 必須為正數")
    if ref_price <= 0:
        raise ValueError("signal_price 必須為正數")
    horizon_days = max(1, min(int(horizon_days), 30))
    stop_loss_pct = max(0.1, min(float(stop_loss_pct), 20.0))
    rows = []
    for row in candles:
        try:
            d = date.fromisoformat(str(row.get("date") or row.get("timestamp") or "")[:10])
            o, h, l, c = (float(row.get(k) or 0) for k in ("open", "high", "low", "close"))
            if min(o, h, l, c) <= 0 or h < max(o, c) or l > min(o, c):
                continue
            rows.append({"date": d.isoformat(), "open": o, "high": h, "low": l, "close": c,
                         "volume": int(float(row.get("volume") or 0))})
        except (TypeError, ValueError):
            continue
    rows.sort(key=lambda x: x["date"])
    by_date = {x["date"]: x for x in rows}
    signal_bar = by_date.get(signal_day.isoformat())
    if not signal_bar:
        return {"ok": False, "status": "DATA_INCOMPLETE", "symbol": symbol, "signal_date": signal_day.isoformat(),
                "signal_price": ref_price, "error": "歷史日 K 沒有訊號日；不推定訊號日價格或結果。", "available_dates": [x["date"] for x in rows[-10:]]}
    after = [x for x in rows if x["date"] > signal_day.isoformat()][:horizon_days]
    if not after:
        return {"ok": False, "status": "DATA_INCOMPLETE", "symbol": symbol, "signal_date": signal_day.isoformat(),
                "signal_price": ref_price, "error": "尚無訊號日之後的完整日 K。", "data_through": rows[-1]["date"] if rows else None}
    max_bar = max(after, key=lambda x: x["high"])
    min_bar = min(after, key=lambda x: x["low"])
    signal_return = (max_bar["high"] / ref_price - 1) * 100
    signal_drawdown = (min_bar["low"] / ref_price - 1) * 100
    entry_bar = after[0]
    entry = entry_bar["open"]
    entry_max_bar = max(after, key=lambda x: x["high"])
    entry_min_bar = min(after, key=lambda x: x["low"])
    mfe = (entry_max_bar["high"] / entry - 1) * 100
    mae = (entry_min_bar["low"] / entry - 1) * 100
    stop = entry * (1 - stop_loss_pct / 100)
    stop_bar = next((x for x in after if x["low"] <= stop), None)
    if stop_bar:
        # Daily candles cannot resolve intraday path or gap/slippage precisely.
        stop_exit = min(stop, stop_bar["open"]) if stop_bar["open"] < stop else stop
        stop_result = {"triggered": True, "date": stop_bar["date"], "theoretical_exit_price": round(stop_exit, 4),
                       "gross_return_pct": round((stop_exit / entry - 1) * 100, 3),
                       "limitation": "僅以日 K 低點判斷停損觸及；未建模逐筆路徑、滑價、漲跌停與交易成本。"}
    else:
        last = after[-1]
        stop_result = {"triggered": False, "date": last["date"], "theoretical_exit_price": last["close"],
                       "gross_return_pct": round((last["close"] / entry - 1) * 100, 3),
                       "limitation": "以觀察期最後一根日 K 收盤作為假設出場，未計交易成本。"}
    return {
        "ok": True, "status": "DAILY_BAR_VALIDATED", "validation_type": "POST_SIGNAL_DAILY_BAR_ONLY",
        "symbol": str(symbol), "signal_date": signal_day.isoformat(), "signal_price": ref_price,
        "signal_day_bar": signal_bar, "data_source_granularity": "daily OHLCV; no 5-minute or tick path used",
        "observation_start": after[0]["date"], "observation_end": after[-1]["date"],
        "requested_horizon_trading_days": horizon_days, "actual_horizon_trading_days": len(after),
        "data_through": rows[-1]["date"],
        "signal_reference_excursion": {"max_high": max_bar["high"], "max_high_date": max_bar["date"],
            "mfe_pct_from_signal_price": round(signal_return, 3), "min_low": min_bar["low"], "min_low_date": min_bar["date"],
            "mae_pct_from_signal_price": round(signal_drawdown, 3)},
        "next_trading_day_open_scenario": {"entry_date": entry_bar["date"], "entry_price": entry,
            "mfe_pct": round(mfe, 3), "mfe_high": entry_max_bar["high"], "mfe_high_date": entry_max_bar["date"],
            "mae_pct": round(mae, 3), "mae_low": entry_min_bar["low"], "mae_low_date": entry_min_bar["date"],
            "stop_loss_pct": stop_loss_pct, "stop_scenario": stop_result},
        "ground_truth_status": "PARTIAL_DAILY_DATA_ONLY",
        "not_proven": ["可成交的 5 分 K 突破時點", "逐筆成交順序", "滑價與交易成本後報酬", "策略統計顯著性", "原始選股規則的因果預測能力"],
        "paper_orders_created": 0, "production_source_modified": False,
    }
