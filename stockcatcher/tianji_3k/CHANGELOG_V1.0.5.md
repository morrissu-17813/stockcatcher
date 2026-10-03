# 天機 3K Production v1.0.5

## Manual Monitor Mode

### 新增

- 新增 `--manual-monitor`。
- 手動啟動後不因非盤中時間直接結束。
- 週末、盤前、盤後均可持續執行 MIS Radar，供本地/線上測試。
- Radar 每輪直接列出實際監控股票：股號、股名、來源、市場、現價、State。
- 顯示 PREMARKET / DYNAMIC / TOTAL 監控數量。
- Ctrl+C 安全停止並釋放 Production lock。

### 保持不變

- `--run` 正式 Production lifecycle 不變。
- Dynamic Discovery 規則不變。
- MIS 仍為盤中市場廣度 Discovery 主來源。
- FinMind 僅做候選歷史補強。
- Fugle 5m 仍只在 State Machine 突破後呼叫。
- Projected Volume >= 1.5x hard gate 不變。
- 不加入 KD、2TON、SMC、權證主力。
