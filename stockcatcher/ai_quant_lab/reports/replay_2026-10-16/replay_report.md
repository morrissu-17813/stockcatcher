# 天機 3K 離線盤中交易重播報告

- 模式：`OFFLINE_PAPER_REPLAY_ONLY`
- 日期：`2026-10-16`
- 原始檔 SHA-256：`778707e002f04a94f37aba0ad924511894663a5ba883d020ff63047dd211f7fe`
- 來源行數：68756

## 流程重建

| 階段 | LOG 可見結果 |
|---|---|
| Stage 0 完整驗證通過 | 345 |
| Stage 0 傳入 Stage 1 | 344 |
| Stage 1 趨勢通過 | 145 |
| Stage 1 傳入 Stage 2 | 145 |
| Stage 2 突破通過 / 未通過 | 2 / 143 |
| Stage 2 傳入 Stage 3 | 2 |
| Stage 3 量能通過 / 未通過 | 2 / 0 |
| 最終 3K PASS | 2 |
| 盤中 Radar cycle | 753 |
| 動態候選事件 / 不重複股票 | 79 / 79 |
| 突破觸發事件 / 不重複股票 | 26 / 20 |
| 預測事件 | 21 |
| LOG 明確記載 Telegram SENT | 21 / 明確送出紀錄 21 |
| MIS 回傳覆蓋率平均 / 最低 / 最高 | 11.13% / 4.08% / 20.24%（有效報價數 / requested） |
| Radar 週期平均 / P95 / 最長 | 20.11 秒 / 20.02 秒 / 33.48 秒 |

## 嚴格模擬交易結果

- 下單策略：FUGLE_5M + STRONG + projected_ratio >= threshold + trigger/snapshot freshness + breakout valid + time/risk gate
- 模擬假定成交：2
- 未下單訊號：19
- 代理收盤淨損益：-2447.27
- 代理報酬率：-0.2447%
- **以上損益不是已驗證策略績效。出場價是最後一筆非空監控表格顯示值，不是可確認的官方收盤價；報價新鮮度未能從 LOG 證明。**

| 股票 | 進場時間 | 模擬進場價 | 股數 | 收盤代理價 | 淨損益（代理） | 狀態 |
|---|---:|---:|---:|---:|---:|---|
| 3167 大量 | 2026-10-16T11:51:17.719+08:00 | 1051.0500 | 95 | 1055.0 | -310.31 | CLOSED_AT_LAST_DISPLAY_MARK_PROXY |
| 4960 誠美材 | 2026-10-16T12:59:21.377+08:00 | 25.7257 | 3887 | 25.35 | -2136.96 | CLOSED_AT_LAST_DISPLAY_MARK_PROXY |

## 三道驗收矩陣

| 驗收項目 | 狀態 |
|---|---|
| 盤前掃描重建 | PASS_WITH_COUNT_GAP |
| 盤中 Radar 重播 | PASS_WITH_LOW_MIS_COVERAGE |
| 紙上交易決策重播 | PASS_SIMULATED_ONLY |
| Supabase 持久化／重啟恢復 | NOT_VERIFIABLE_FROM_THIS_LOG |
| 盤中停損／停利路徑 | NOT_VERIFIABLE_NO_FRESH_FULL_PRICE_PATH |
| 真實交易準備度 | **NO_GO** |

> Fault-gate / order-lifecycle unit tests cover persistence-not-ready, stale quotes, daily duplicate prevention, position limits, partial-fill state, UNKNOWN-order handling, and fresh-quote stop/target decisions. They are software-level tests, not a real Supabase outage/restart or broker-fill integration test.

## 收盤驗收

- Ground Truth 狀態：**FAILED**
- cutoff 摘要：`{"predictions": 21, "unavailable": 21, "available": 0}`
- Ground Truth 錯誤次數：16
- 盤中歷史資料不完整警告：42
- 涉及不重複股票：2408, 2609, 3504, 3529, 3535, 3580, 3704, 3718, 4147, 4916, 4967, 5202, 6112, 6742, 8358
- 無法識別股票代碼的警告筆數：0

## 重要限制

- GitHub Actions LOG 是執行紀錄，不是完整 tick/1m/5m OHLCV 歷史行情。
- 監控表格的價格行無法證明報價時間與新鮮度；只能作為收盤代理價情境，不能當官方收盤價。
- 沒有部分成交、委託回報或券商交易紀錄；訂單／成交是本次模擬，不是實際成交。
- Ground Truth cutoff 顯示當日所有預測不可驗證，因此不能把模擬損益當成策略績效或命中率。
