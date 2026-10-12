# 天機 3K Production v1.2.3

## 目的
降低 MIS Radar 被 Fugle 5 分 K 呼叫阻塞的風險，確保所有監控股票先更新最新有效快照，再處理外部確認。

## 六項最佳化
1. **先更新全池狀態**：每輪先更新所有可用的最新有效 MIS 快照，再消化已完成的 Fugle 工作、排入新工作。
2. **Fugle 非同步佇列**：最多 4 個 worker；Radar 不等待 Fugle HTTP 回應。健康檢查也改為非同步。
3. **最新快照管理**：每檔股票保存最新有效快照與本機接收時間。通知建立時使用最新快照，不沿用 API 呼叫前的舊價格。
4. **5M K 棒快取**：Fugle 5M 資料加入 20 秒快取，減少同一時間窗的重複 HTTP 請求。
5. **重試節流**：同一檔股票的 Fugle 確認最短間隔 30 秒，避免每個 Radar 週期重複呼叫。
6. **發送前新鮮度與可觀測性**：快照超過 45 秒未更新時不以舊價發送；增加 Radar、狀態更新、Fugle 請求、Dynamic Discovery 耗時紀錄，並記錄觸發價／通知快照。

## 保護規則
- MIS 現價無效、未成交或缺少有效價格時，不覆蓋最後有效快照，也不推進狀態機。
- 無效快照不會被當成前收盤價，也不會因而判定突破失效。
- Fugle 延遲結果若回來時狀態已失效，直接丟棄，不復活舊觸發。
- EARLY 仍使用 5M 結構 OR 量能的既有條件；Projected Volume 不作為 EARLY 硬性門檻。STRONG／MOMENTUM 的既有規則保留。
- PREMARKET、DYNAMIC 共用同一個盤中訊號流程；未更動 Stage 0～3 選股條件。

## 新增觀測 Log
- `RADAR PHASE`
- `RADAR TIMING`
- `FUGLE 5M QUEUED`
- `FUGLE REQUEST TIMING`
- `FUGLE 5M CACHE HIT`
- `SIGNAL WAITING FOR FRESH MIS`
- `INTRADAY_3K_PREDICTION` 顯示當次使用的最新價格與突破基準

## 測試
- 完整測試套件：121 passed。
