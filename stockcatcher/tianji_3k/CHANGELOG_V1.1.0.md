# Tianji 3K Production v1.1.0

## 2026-10-06 盤中 Log 修正版

本版只修復今天實盤 Log 已證實的阻斷問題，不修改 3K Stage 0～3、MIS breakout gate、Fugle 5M micro-confirmation 1.2x、Projected Volume 1.5x、Telegram notification gate。

### 1. 修正 TRIGGERED → Fugle 之前的 datetime 型別錯誤
- Production `MarketSnapshot.observed_at` 是 ISO 字串。
- 舊程式在新觸發時直接呼叫 `snap.observed_at.isoformat()`，導致：
  `AttributeError: 'str' object has no attribute 'isoformat'`
- 該錯誤發生在 Fugle request 前，因此今天大量 `TRIGGERED` 後根本沒有進入 Fugle 5M。
- v1.1.0 統一以 `_iso_timestamp()` / `_as_datetime()` 處理 live/persisted timestamps。

### 2. Fugle 5M 外部依賴隔離
- `FugleAPIError` 繼續隔離 401/網路/JSON 錯誤。
- 新增一般 Exception fallback；任何單檔 Fugle adapter/runtime 錯誤都只影響該 symbol。
- `fugle_pending` 保留，下一 Radar cycle 可重試。

### 3. 完整可觀測鏈路
- `BREAKOUT TRIGGER`
- `FUGLE 5M REQUEST`
- `FUGLE 5M SUCCESS / ERROR / REJECT`
- `PROJECTED VOLUME REJECT`
- `INTRADAY_3K_PREDICTION`
- `NOTIFICATION`

### 4. 驗證
- pytest：111 passed / 0 failed
- compileall：通過
- CLI：`--run` / `--intraday-once` / `--manual-monitor` / `--ground-truth-once` 通過
- 新增端到端單元整合測試：兩個 distinct MIS identities → TRIGGERED → Fugle 5M → projected volume → prediction ledger。
