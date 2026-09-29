REQUIRED_KEYS = ("symbol", "close", "volume", "prev_close", "high", "prev_high", "prev2_high")


def stage0_data_gate(snapshot: dict) -> dict:
    missing = [k for k in REQUIRED_KEYS if snapshot.get(k) is None]
    if missing:
        return {"passed": False, "reason": f"missing:{','.join(missing)}"}
    return {"passed": True, "reason": "ok"}


def stage1_direction(snapshot: dict) -> dict:
    week_kd = snapshot.get("week_kd_golden_cross", False)
    day_kd = snapshot.get("day_kd_up", False)
    return {
        "week_kd_golden_cross": bool(week_kd),
        "day_kd_up": bool(day_kd),
        "passed": bool(week_kd and day_kd),
    }


def stage2_breakout(snapshot: dict) -> dict:
    high = float(snapshot["high"])
    prev_high = float(snapshot["prev_high"])
    prev2_high = float(snapshot["prev2_high"])
    prev_close = float(snapshot["prev_close"])
    close = float(snapshot["close"])
    volume = float(snapshot["volume"])
    prev_volume = float(snapshot.get("prev_volume", 0) or 0)

    return {
        "breakout": high > prev_high and high > prev2_high,
        "gain_pct": (close / prev_close - 1) * 100 if prev_close else 0,
        "volume_ratio": volume / prev_volume if prev_volume else None,
    }
