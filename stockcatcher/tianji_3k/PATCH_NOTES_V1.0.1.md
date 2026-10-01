# 天機 3K Production v1.0.1 修補說明

基準版本：`tianji_3k_Production_v1.0.zip`

## 1. 歷史 K / FinMind 單股失敗容錯
- 單一 symbol 的歷史 K 取得、FinMind 呼叫或有效 K 棒不足等一般例外，最多重試 3 次。
- 第 3 次仍失敗：記錄 `skipped_symbols` 與 `symbol_failures`，隔離該 symbol，繼續下一筆。
- 全部候選完成後狀態可為 `COMPLETE_WITH_SKIPS`。
- 被跳過的 symbol 不進入本輪 Stage 1→2→3，避免殘缺歷史資料被誤判。
- FinMind rolling budget exhaustion 仍維持原本 PAUSED_BUDGET 機制，不會假裝資料成功。

## 2. Production lifecycle 容錯
- `PREMARKET` 建池例外：記錄事件並等待下一輪重試。
- `RADAR` 階段若需要重新建池且建池失敗：記錄事件並等待下一輪，不終止整個 runner。

## 3. 盤中 Radar 實際接線
目前 Production Runner 已包含：
`Final 3K Pool → MIS 20s Radar → State Machine → Volume Projection → INTRADAY_3K_PREDICTION → Telegram`

正式交易日必須使用：
`python -m tianji_3k --run`

單次盤中測試使用：
`python -m tianji_3k --intraday-once --no-telegram`

注意：不帶參數的 `python -m tianji_3k` 目前仍只建立盤前觀察池，不會進入盤中 Radar。

## 4. 實際線上版紀錄判讀
2026-09-30/2026-10-01 的既有紀錄只有 `PREMARKET_WATCHLIST`，沒有 `RADAR_COMPLETE`、`RADAR_ERROR` 或 `INTRADAY_3K_PREDICTION`。因此當天實際執行鏈沒有進入盤中 Radar；Telegram 本身不是主要斷點。
