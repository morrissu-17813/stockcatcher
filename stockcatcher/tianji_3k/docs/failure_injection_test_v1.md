# 天機 3K — 完整交易日故障注入測試 V1

## 目的

Failure Injection Test 不是測策略是否選對股票，而是驗證盤中 Production 在「資料/API/程序/通知/重啟」異常時，是否仍能維持可恢復、可追溯、不可重複的 Prediction Ledger。

## 注入情境

1. `MIS_TIMEOUT`：MIS timeout，保留最後成功 checkpoint。
2. `MIS_EMPTY_PAYLOAD`：空 payload，不污染成功狀態。
3. `PROCESS_CRASH_AFTER_PREDICTION`：Prediction 已落盤後程序中斷，重啟不得產生第二個 prediction_id。
4. `TELEGRAM_SEND_FAILURE`：Telegram 發送失敗，重試後只能有一個 SENT 結果。
5. `PROCESS_CRASH_AFTER_NOTIFICATION`：通知完成後程序中斷，重啟不得重複通知。
6. `DUPLICATE_SNAPSHOT`：同一 data_identity 重送，不得作為第二次有效確認。
7. `GROUND_TRUTH_RETRY`：Ground Truth 重試，不得產生第二筆同 prediction_id 的 validation。

## 驗證不變量

- Prediction ID 唯一。
- Prediction event immutable。
- Notification retry idempotent。
- State machine 可從 durable event 恢復。
- 同一 data identity 不得重複確認。
- 每個 Prediction 最終最多一筆 `PREDICTION_VALIDATION`。
- Ground Truth 不修改原 Prediction。
- 最終 checkpoint 必須 `clean_shutdown=true`。

## 執行

```powershell
python -m tianji_3k.tools.failure_injection
```

測試只使用 synthetic snapshots，不呼叫 MIS、Fugle 或 Telegram，因此可以離線重複執行。

## 為什麼必要

3K 預判一旦進入真實盤中，最大的風險不只來自策略錯誤，而來自「系統知道發生過什麼，但資料沒有完整留下」：程序 crash、API timeout、通知失敗、重啟重複觸發、盤後驗證重複寫入，都可能讓命中率統計失真。Failure Injection Test 用可重現的故障強制驗證這些邊界條件，確保歷史驗證資料可信。
