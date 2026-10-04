# 天機 3K Production v1.0.8

## 本版定位
以 v1.0.7 Production 為基底，僅修正已確認的資料契約與恢復問題，不改動 3K Stage 0~3、MIS State Machine、Fugle 5m、Projected Volume >= 1.5x、Telegram 通知核心邏輯。

## 修正
1. **MIS 成交量單位修正**
   - TWSE/TPEx MIS `v` 明確視為「張」(lots)。
   - MIS raw 同時提供 `cumulative_volume_lots` 與 `cumulative_volume_shares`。
   - Dynamic Discovery 優先使用 `cumulative_volume_lots`，避免再除以 1000 導致 1000 倍低估。
   - 舊 replay/test payload 若只有 `cumulative_volume`，仍保留 shares→lots 相容路徑。
   - MarketSnapshot 對明確 LOTS payload 轉回 shares 後再進入既有模型，維持原有內部資料契約。

2. **Fugle 5 分鐘 API 參數修正**
   - 移除官方 intraday candles 未列出的 `limit` query parameter。
   - 仍只取已完成的 5 分鐘 K 棒，3K micro-breakout 規則不變。

3. **盤前 Pool 狀態恢復修正**
   - 新程序直接載入既有 `cache/pools/{trade_date}.json` 時，從 Pool 的 `date/latest_date` 恢復 `latest_completed_date`。
   - 若 Pool 無日期，再從 `cache/data_freshness.json` 嘗試恢復。
   - 避免 Dynamic Discovery 因新程序沒有 T-1 日期而跳過歷史資料 enrichment。

4. **手動監控**
   - 保留 v1.0.7 已存在的 `--manual-monitor`。
   - 本地互動式 `--run` 在非盤中時間可自動進入 Manual Monitor；CI/非互動 Production lifecycle 維持原規則。

## 未修改
- 3K Stage 0~3 規則
- 不加入週 KD / 日 KD
- Dynamic Discovery 仍為 MIS market-wide gate + 每 cycle 最多 3 檔歷史 enrichment
- MIS → State Machine → Fugle 5m → Projected Volume >=1.5x → Notification Gate → Telegram
- 不加入 2TON / SMC 金蛋蛋
- Telegram only；LINE 不在 V1.0

## 驗證
- `pytest -q`: 106 passed, 0 failed
- `python -m compileall -q .`: PASS
