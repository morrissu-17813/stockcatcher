# 天機 3K 盤中預判／歷史驗證資料設計 V2.0

## 核心原則

1. 每個交易日是獨立 round。
2. `PREMARKET_WATCHLIST` 只是觀察池，不是盤中訊號。
3. `INTRADAY_3K_PREDICTION` 是不可覆寫的預判事實。
4. Telegram 發送結果以獨立 notification event 追加，不修改原始 prediction。
5. Ground Truth 獨立保存，不覆寫 prediction。
6. 同一 MIS data identity 不得重複計入連續兩次確認。
7. `up_pct >= 9.50%` 不發 Telegram，但仍建立 SUPPRESSED 紀錄。
8. 盤中價格突破若無法滿足預估量比 >= 1.5，只記錄 `BREAKOUT_PRICE_TRIGGER_REJECTED`，不升級為 3K 預判。

## 檔案

```text
predictions/YYYY-MM-DD/SYMBOL/
├── context.json
├── events.jsonl
└── ground_truth.json

validation/
├── daily/YYYY-MM-DD.json
├── daily_events/YYYY-MM-DD.jsonl
├── master_prediction_log.jsonl
├── master_prediction_validation_log.jsonl
└── master_ground_truth_log.jsonl
```

## 預判與驗證的一對一關係

每個 `prediction_id` 都會在收盤後產生一筆 `PREDICTION_VALIDATION`。因此同一股票同一天若重新觸發兩次，兩個 prediction_id 都各自保留並分別驗證。
