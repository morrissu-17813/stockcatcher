# 天機 3K Manual Monitor Mode v1.0.5

## 目的

提供本地或線上人工啟動的持續監控模式，避免因目前不是台股盤中時間而直接結束，方便驗證 Dynamic Discovery、MIS Radar、State Machine 與監控清單。

## 啟動

```powershell
python -m tianji_3k --manual-monitor --no-telegram
```

若要連同 Telegram 測試：

```powershell
python -m tianji_3k --manual-monitor
```

## 行為

- 明確進入 `MANUAL MONITOR MODE` 後，不受 `TradingSession` 的 `PREMARKET_WAIT / PREMARKET / RADAR / GROUND_TRUTH / STOP` 結束條件限制。
- 即使週末、盤後或盤前，也會持續執行 MIS Radar。
- 每個 Radar cycle 會重新執行既有 Dynamic Discovery 流程。
- 監控表會列出目前實際進入 Radar 的：
  - 股號
  - 股名
  - 來源：`PREMARKET` 或 `DYNAMIC`
  - 市場：TSE / TPEx
  - MIS 現價
  - State Machine 狀態
- 每輪結束顯示 `PREMARKET / DYNAMIC / TOTAL` 數量。
- Ctrl+C 會安全停止 Manual Monitor，不會留下 Production lock。

## 與 Production 的隔離

正式 `--run` 完全維持原本交易日生命周期：

`08:20 PREMARKET → 09:00 RADAR → 13:30 GROUND_TRUTH → 13:35 STOP`

`--manual-monitor` 是獨立的人工測試模式，不改變正式排程，也不代表當下市場一定處於真實盤中。

## API 行為

Manual Monitor 沿用 Production v1.0.4 的資料分工：

`MIS market-wide → Dynamic Gate → 每輪最多 3 檔歷史補強 → State Machine → Fugle 5m → Projected Volume`

不新增 KD、2TON、SMC 或權證主力邏輯。
