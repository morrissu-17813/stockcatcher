"""Deterministic, auditable daily-bar 3K-style backtest primitives.

This is a research report generator, not an execution engine. It uses only the
provided completed daily bars and labels the tested rule/assumptions explicitly.
"""
from __future__ import annotations
from typing import Any


def _num(row: dict[str, Any], *keys: str) -> float:
    for key in keys:
        try:
            value = row.get(key)
            if value not in (None, "", "-"):
                return float(value)
        except (TypeError, ValueError):
            continue
    return 0.0


def _kd(highs: list[float], lows: list[float], closes: list[float], period: int = 9) -> tuple[float, float]:
    k, d = 50.0, 50.0
    for i in range(period - 1, len(closes)):
        hh = max(highs[i-period+1:i+1]); ll = min(lows[i-period+1:i+1])
        rsv = 50.0 if hh <= ll else (closes[i] - ll) / (hh - ll) * 100.0
        k = (2.0 / 3.0) * k + (1.0 / 3.0) * rsv
        d = (2.0 / 3.0) * d + (1.0 / 3.0) * k
    return k, d


def run_backtest(symbol: str, bars: list[dict[str, Any]], fee_rate: float = 0.001425,
                 stop_loss_pct: float = 0.02, max_holding_bars: int = 5) -> dict[str, Any]:
    rows = []
    for bar in bars:
        date = str(bar.get("date") or bar.get("timestamp") or "")[:10]
        close = _num(bar, "close", "Close")
        open_ = _num(bar, "open", "Open")
        high = _num(bar, "high", "max", "High")
        low = _num(bar, "low", "min", "Low")
        # Daily historical volume from Fugle/FinMind may be shares; convert explicitly to lots.
        volume = _num(bar, "volume_lots")
        if not volume:
            volume = _num(bar, "volume", "Trading_Volume", "TradeVolume") / 1000.0
        if date and min(close, open_, high, low) > 0:
            rows.append({"date": date, "open": open_, "high": high, "low": low, "close": close, "volume_lots": volume})
    rows.sort(key=lambda r: r["date"])
    if len(rows) < 30:
        return {"ok": False, "symbol": symbol, "error": "至少需要 30 根完整日 K 才能進行初步回測", "bars": len(rows)}

    # Aggregate completed daily bars to weekly bars; KD uses only completed weeks.
    weeks: dict[str, list[dict[str, Any]]] = {}
    import datetime as _dt
    for row in rows:
        try: d = _dt.date.fromisoformat(row["date"])
        except ValueError: continue
        iso = d.isocalendar(); key = f"{iso.year}-W{iso.week:02d}"
        weeks.setdefault(key, []).append(row)
    weekly = []
    for key, group in weeks.items():
        weekly.append({"date": key, "high": max(x["high"] for x in group), "low": min(x["low"] for x in group), "close": group[-1]["close"]})
    weekly.sort(key=lambda x: x["date"])
    wh = [x["high"] for x in weekly]; wl = [x["low"] for x in weekly]; wc = [x["close"] for x in weekly]
    weekly_cross_indices = set()
    for wi in range(1, len(weekly)):
        kp, dp = _kd(wh[:wi], wl[:wi], wc[:wi])
        kn, dn = _kd(wh[:wi+1], wl[:wi+1], wc[:wi+1])
        if kp <= dp and kn > dn:
            weekly_cross_indices.add(wi)
    signals = []
    for i in range(22, len(rows)):
        cur, prev1, prev2 = rows[i], rows[i-1], rows[i-2]
        if cur["date"][:7] != prev1["date"][:7]: pass
        # Only use weeks that had fully closed before the signal day; recent cross window is 3 weeks.
        cur_day = _dt.date.fromisoformat(cur["date"])
        cur_iso = cur_day.isocalendar(); cur_week_key = f"{cur_iso.year}-W{cur_iso.week:02d}"
        week_idx = next((j for j, w in enumerate(weekly) if w["date"] == cur_week_key), len(weekly))
        completed_idx = week_idx - 1
        week_cross = completed_idx in weekly_cross_indices or completed_idx-1 in weekly_cross_indices or completed_idx-2 in weekly_cross_indices
        dh = [x["high"] for x in rows[:i+1]]; dl = [x["low"] for x in rows[:i+1]]; dc = [x["close"] for x in rows[:i+1]]
        dk_prev, dd_prev = _kd(dh[:-1], dl[:-1], dc[:-1]); dk_now, dd_now = _kd(dh, dl, dc)
        daily_k_up = dk_now > dk_prev and dd_now >= dd_prev
        vma5 = sum(x["volume_lots"] for x in rows[i-5:i]) / 5
        vma20 = sum(x["volume_lots"] for x in rows[i-20:i]) / 20
        gain = (cur["close"] / prev1["close"] - 1) * 100 if prev1["close"] else 0
        red = cur["close"] > cur["open"]
        breakout = cur["high"] > max(prev1["high"], prev2["high"])
        volume_ok = cur["volume_lots"] > prev1["volume_lots"] and vma5 >= 1000 and (vma5 > 0 and cur["volume_lots"] / vma5 >= 1.5)
        if breakout and red and gain >= 4 and volume_ok and daily_k_up and week_cross:
            signals.append({"index": i, "date": cur["date"], "close": cur["close"], "weekly_kd_golden_cross": week_cross,
                            "daily_k_up": daily_k_up, "gain_pct": gain, "volume_lots": cur["volume_lots"], "vma5_lots": vma5,
                            "volume_ratio": cur["volume_lots"] / vma5 if vma5 else None,
                            "weekly_kd_status": "PASS" if week_cross else "NOT_CONFIRMED"})
    # Conservative paper simulation: enter at next bar open; stop-loss at 2%; exit at stop or max holding bars close.
    trades = []
    for signal in signals:
        entry_i = signal["index"] + 1
        if entry_i >= len(rows): continue
        entry = rows[entry_i]["open"]
        if entry <= 0: continue
        stop = entry * (1 - stop_loss_pct)
        exit_i = min(entry_i + max_holding_bars - 1, len(rows)-1)
        exit_price = rows[exit_i]["close"]; exit_reason = "持有期到期收盤"
        for j in range(entry_i, exit_i+1):
            if rows[j]["low"] <= stop:
                exit_price = stop; exit_i = j; exit_reason = "停損觸發"; break
        gross = (exit_price / entry) - 1
        net = gross - (fee_rate * 2)
        trades.append({"signal_date": signal["date"], "entry_date": rows[entry_i]["date"], "exit_date": rows[exit_i]["date"],
                       "entry_price": round(entry, 4), "exit_price": round(exit_price, 4), "return_pct": round(net*100, 3),
                       "gross_return_pct": round(gross*100, 3), "exit_reason": exit_reason})
    wins = [t for t in trades if t["return_pct"] > 0]
    returns = [t["return_pct"] for t in trades]
    equity = peak = 100.0; max_dd = 0.0
    for ret in returns:
        equity *= 1 + ret/100; peak = max(peak, equity)
        max_dd = max(max_dd, (peak-equity)/peak*100 if peak else 0)
    return {"ok": True, "symbol": symbol, "bars": len(rows), "first_date": rows[0]["date"], "last_date": rows[-1]["date"],
            "strategy": "3K 日 K 初步回測（週 KD 交叉標記、日 KD 向上、突破、紅 K 漲幅≥4%、成交量>昨日、VMA5≥1000 張、量比≥1.5）",
            "assumptions": ["進場：訊號日下一交易日開盤", f"停損：-{stop_loss_pct*100:.1f}%", f"最長持有：{max_holding_bars} 根日 K", "單邊手續費率依參數估算；未計滑價、稅費優惠與漲跌停無法成交風險", "週 KD 以已完成週 K 計算；此為初步歷史回測，非即時交易承諾"],
            "signals": len(signals), "trades": len(trades), "win_rate_pct": round(len(wins)/len(trades)*100, 2) if trades else 0,
            "avg_return_pct": round(sum(returns)/len(returns), 3) if returns else 0, "total_return_pct": round((equity/100-1)*100, 3),
            "max_drawdown_pct": round(max_dd, 3), "trade_rows": trades, "signal_rows": [{k:v for k,v in s.items() if k!="index"} for s in signals]}
