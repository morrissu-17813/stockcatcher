# 天機 3K v1.2.12 — Prediction Ledger 完整化

## 版本目標

強化正式 3K 訊號的可追溯性、資料一致性與修復能力。此版本只處理 Prediction Ledger；不改 Stage 0–3 選股條件、MIS 輪詢頻率、Telegram 通知流程、Fugle／FinMind 呼叫頻率或正式交易訊號門檻。

## 變更

- Prediction event schema 升級為 `prediction-v2.2`，保留原始 `context`、`trigger_snapshot`、`volume_snapshot`、`notification`，另新增標準化 `signal` 欄位供後續統計使用。
- 新增 `event_id`、`recorded_at`、`source`、`record_hash`，便於追溯、分類及完整性檢查。
- `create_prediction()` 在 Ledger 邊界加入相同 snapshot ID + 相同觀測時間的冪等保護；不同觀測時間仍保留為不同訊號。
- 每檔股票每日 `events.jsonl` 為正式訊號 canonical source；`master_prediction_log.jsonl` 定位為可重建索引。
- 新增 `audit()`，檢查重複 prediction_id、JSONL 格式錯誤、record hash 不一致及 master index 缺漏／孤兒紀錄。
- 新增 `rebuild_master_prediction_log()` 與 CLI：`python -m tianji_3k.validation.ledger_audit`。
- 保留既有 Ground Truth 寫入行為，避免本版改變收盤驗證流程。

## 不變項目

- Stage 0–3 條件與閾值不變。
- MIS Radar 輪詢頻率及快照資料來源不變。
- Telegram 通知格式、時機、去重與失敗處理流程不變。
- 不新增行情 API 呼叫，不改 runner 主流程。
- 不加入 2TON／SMC 正式選股條件。

## 驗證

- `python -X utf8 -m pytest -q`：165 passed。
- `python -m compileall -q .`：通過。
- 新增測試涵蓋 schema 標準化、相同快照冪等、master index 重建與完整性稽核。

## 限制

- `record_hash` 用於偵測資料意外變更，不是數位簽章或防竄改安全機制。
- 本版 append locking 保護同一 Python 程序內的執行緒；跨程序仍依賴 Production 既有 process lock。
- master log 可由 per-symbol canonical events 重建；不可把 master log 當唯一資料來源。
