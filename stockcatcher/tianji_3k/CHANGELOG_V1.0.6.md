# 天機 3K Production v1.0.6

## Test Baseline / Liveness Maintenance

### 修正

- 修正 CacheFirstDailyProvider 個別股票合法停牌測試契約：Production initializer 仍使用 `allow_symbol_non_trading=True`，避免把全球交易日缺少個股 K 棒誤判為歷史資料損壞。
- 恢復 `TianjiProductionRunner._finalize_close_snapshot()` 官方收盤快照邊界，僅使用 TWSE/TPEx official daily provider，不消耗 FinMind budget。
- 修正 Radar 在 `_premarket_built=True` 且 watchlist 為空時反覆重建盤前池的問題，避免無意義觸發 Trading Calendar / FinMind bootstrap。

### 驗證

- Full pytest: **103 passed / 0 failed**
- 未修改 3K Stage 0~3 規則。
- 未修改 Dynamic Discovery gate。
- 未修改 State Machine / Fugle 5m / Projected Volume 1.5x gate。
- 未修改正式 `--run` lifecycle。
- v1.0.5 `--manual-monitor` 行為保留。
