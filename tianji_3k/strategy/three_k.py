def evaluate_three_k(snapshot: dict, direction: dict, breakout: dict) -> dict:
    score = 0
    reasons = []

    if direction["week_kd_golden_cross"]:
        score += 25
        reasons.append("週KD黃金交叉")
    if direction["day_kd_up"]:
        score += 20
        reasons.append("日KD向上")
    if breakout["breakout"]:
        score += 30
        reasons.append("突破前兩日高點")

    volume_ratio = breakout["volume_ratio"]
    if volume_ratio is not None and volume_ratio >= 1.5:
        score += 15
        reasons.append("量能放大")

    if breakout["gain_pct"] >= 4:
        score += 10
        reasons.append("紅K漲幅>=4%")

    status = "TRIGGER" if score >= 70 else "WATCH" if score >= 45 else "REJECT"
    return {"status": status, "score": score, "reason": "、".join(reasons) or "條件不足"}
