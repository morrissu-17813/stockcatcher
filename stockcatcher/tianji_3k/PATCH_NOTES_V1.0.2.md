# Tianji 3K Production v1.0.2

## 可觀測性 LOG 強化

本版本以 Production v1.0.1 為基準，僅增加盤中監控可觀測性，不修改 3K 選股、Stage 0~3、State Machine、MIS 輪詢頻率、量能預測或 Telegram Gate。

### 1. 每次 RADAR 輪詢顯示監控清單

每次既有 MIS 輪詢完成後，直接使用同一批回傳資料在 GitHub Actions Console 顯示：
- 股號
- 股名
- 現價

並顯示監控池數量、MIS 實際回傳數量，以及下一次監控秒數。

### 2. 啟動 LOG

Production `--run` 啟動時顯示：
- trade date
- RADAR interval
- Telegram ON/OFF

### 3. Phase LOG

Phase 發生切換時顯示：
- PREMARKET_WAIT
- PREMARKET
- RADAR
- GROUND_TRUTH
- STOP

### 4. 異常 LOG

RADAR 發生 MIS fetch error 或 runner-level fatal error 時，直接在 Console 顯示錯誤類型與訊息；既有 recovery ledger 行為保留。

### 操作指令

```bash
cd stockcatcher
python -u -m tianji_3k --run
```
