# 天機 3K V1.2.3.2-P1

## 修正：Cache Calendar Isolation

`CacheFirstDailyProvider` 不再在 `calendar=None` 時自動建立 `TaiwanTradingCalendar`。

### Production
Production Runner / Daily Refresh Manager 應明確傳入 `TaiwanTradingCalendar`，因此正式環境仍使用台灣交易日曆。

### Offline / Unit Test
若沒有傳入 Calendar，`CacheFirstDailyProvider` 使用 `pandas.bdate_range()` 作為離線 weekday fallback，且不會從此 Provider 隱式觸發 FinMind。

### 保留
- FinMind 580 requests/hour rolling safety budget
- Cache-first / incremental fetch orchestration
- Trading Calendar production behavior
- Data integrity validation
- Atomic cache writes

## 安裝原則
本包以 V1.2.3.2 cache-integrity-verified source 為基底，只覆蓋 `tianji_3k` 對應檔案；不要覆蓋根目錄 `.env`。
