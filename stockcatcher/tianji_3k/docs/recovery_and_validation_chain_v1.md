# 天機 3K：盤中模擬、錯誤恢復與 Prediction Ledger 驗證鏈

## 1. 三層資料責任

- `predictions/YYYY-MM-DD/SYMBOL/events.jsonl`: 不可覆寫的 Prediction / Radar / Notification 事件。
- `predictions/YYYY-MM-DD/runtime_state.json`: 可重建的快速 runtime checkpoint。
- `predictions/runtime_checkpoint.json`: 程式存活與最後 checkpoint 狀態。
- `validation/recovery_events/YYYY-MM-DD.jsonl`: 啟停、錯誤、恢復、Radar 完成等營運事件。
- `validation/master_prediction_validation_log.jsonl`: Prediction → Ground Truth 的驗證鏈。

Prediction 是來源事實；runtime state 不是來源事實。程式重啟時優先從 Ledger 重新建構狀態。

## 2. Crash Recovery

安全順序：

1. 建立 Prediction event。
2. Telegram 發送。
3. 寫入 Notification event。
4. runtime checkpoint 更新。

若程式在 1～3 任一窗口中斷，重新啟動時：

- Ledger 已有 Prediction → 不重新建立 Prediction。
- 狀態機由 `RADAR_STATE` / `INTRADAY_3K_PREDICTION` 恢復。
- Telegram 尚未確認 `SENT` → `reconcile_pending_notifications()` 可安全重送。
- 已 `SENT` → 不重送。

## 3. 盤中模擬器

輸入 JSON array 或 JSONL，格式使用 MIS Snapshot 欄位：

`symbol, observed_at, current_price, previous_close, today_open, cumulative_volume, up_pct, is_traded, data_identity`

可使用：

```powershell
python -m tianji_3k --simulate snapshots.json --breakout-level 116
```

模擬器使用與 Production 相同的 `MarketSnapshot` 與 `IntradayStateMachine`，因此可驗證：

- 兩個不同 data identity 才能形成有效確認
- duplicate snapshot 不計第二次
- Triggered 後必須失效才可 rearm
- rearm 後可形成新的 Prediction trigger

## 4. Prediction Ledger 驗證鏈

每一筆 Prediction 有唯一 `prediction_id`。Ground Truth 不覆寫 Prediction，而是產生：

`prediction_id → PREDICTION_VALIDATION → chain_hash`

`chain_hash` 由 prediction_id、trigger snapshot、prediction time、Ground Truth 日期、Ground Truth 結果及收盤價計算，可用於日後稽核。
