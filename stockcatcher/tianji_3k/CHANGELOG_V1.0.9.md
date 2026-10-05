# Tianji 3K Production v1.0.9

## 目的
本版是 2026-10-05 盤中實測後的 Production 修正版。只修復盤中資料源韌性、可觀測性與重啟恢復，不修改既有 3K Stage 0～3、MIS breakout gate、Fugle 5M micro-confirmation、Projected Volume >= 1.5x 或 Telegram 通知規則。

## 本版調整
1. **Fugle 401 / 網路錯誤隔離**
   - `FugleProvider` 將 HTTP / request / JSON 錯誤轉為 `FugleAPIError`。
   - Fugle 失敗不再把整個 Radar cycle 升級成 `RADAR FATAL ERROR`。
   - 受影響股票保留待確認狀態，Radar 繼續監控。

2. **Fugle Token 一次性 Health Check**
   - 每次 Production process 第一次 Radar cycle 只做一次 5M API health check。
   - 成功：`🟢 FUGLE HEALTH CHECK | status=OK`。
   - 401：`🔴 FUGLE HEALTH CHECK | status=HTTP_401 | RADAR=CONTINUE`。
   - 不需要等到股票真正突破才知道 Token 是否有效。

3. **Fugle 5M 可觀測性**
   - 新增 `FUGLE 5M REQUEST`。
   - 成功：`FUGLE 5M SUCCESS`。
   - API 錯誤：`FUGLE 5M ERROR`。
   - Micro confirmation 不成立：`FUGLE 5M REJECT`。
   - Projected Volume 不足：`PROJECTED VOLUME REJECT`。

4. **TRIGGERED 與 Fugle Confirmation 分離**
   - `TRIGGERED` 僅代表 MIS State Machine 已完成兩個 distinct identity 的價格觸發。
   - Fugle 5M confirmation 使用 durable `fugle_pending` 管理。
   - Fugle 暫時 401 / timeout / 無足夠 5M K 時，不會要求重新觸發價格 State。
   - 後續 Radar cycle 可重新嘗試 Fugle。

5. **盤中重啟恢復**
   - `runtime_state.json` 持久化 `states` 與 `fugle_pending`。
   - State transition 在進入 Fugle 前即先寫入 ledger / runtime checkpoint。
   - 程式在 Fugle request 中斷時，重啟後仍能恢復原本的 trigger / pending 狀態。

## API 合約確認
依 Fugle 官方文件：股票盤中 K 線使用 `GET /intraday/candles/{symbol}`、`timeframe=5`，Authentication 使用 `X-API-KEY`；整股盤中 K 線 `volume` 單位為成交張數。官方 Fugle Developer Docs 已確認上述 endpoint、timeframe 與 X-API-KEY contract。

## 驗證
- 完整 pytest：**108 passed / 0 failed**。
- `py_compile`：runner / Fugle / state machine 全部通過。
- `--preflight`：程式檢查全部通過；本執行環境沒有正式 `FUGLE_API_KEY`、Telegram Secrets，因此 `shared_env=false` 是預期結果。
- 真正的 Fugle Token 是否有效，必須在你的正式環境執行 Health Check 才能作最終確認。
