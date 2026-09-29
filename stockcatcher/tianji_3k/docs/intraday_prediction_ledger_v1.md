# 天機 3K 盤中預判／歷史驗證資料設計 V1.0

## 每日輪次

T-1 收盤 → Stage 0~3 → T 日 Final 3K Pool（盤前觀察池） → T 日 MIS Radar → INTRADAY_3K_PREDICTION → T 日 13:30~13:35 Ground Truth。

昨日預判不會移植成今日訊號；只會保留在 `predictions/` 與 `validation/` 作為歷史驗證資料。

## 事件不可覆寫

- `context.json`：盤前固定條件
- `events.jsonl`：盤中狀態、預判、通知與抑制事件，append-only
- `ground_truth.json`：收盤驗證，獨立寫入
- `validation/master_prediction_log.jsonl`：跨日預測總帳
- `validation/master_ground_truth_log.jsonl`：跨日 Ground Truth 總帳
- `validation/daily/YYYY-MM-DD.json`：每日統計

## Telegram 類型

- `🌅 PREMARKET_WATCHLIST`：每日一次，觀察池，不是訊號。
- `🔥 INTRADAY_3K_PREDICTION`：盤中有效突破後的預判事件。
- `🏁 GROUND_TRUTH`：收盤驗證。

## +9.5% 通知閘門

`up_pct >= 9.50%` 時不發 Telegram，但仍建立 Prediction / SUPPRESSED 紀錄。

`9.49%` 可通知；`9.50%` 不可通知。
