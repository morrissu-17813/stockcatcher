# 天機 3K Production Data Integrity V1

## 核心原則

正式營運採用：

**乾淨初始化 → 增量更新 → Trading Calendar 驅動缺日判定 → 缺日自動補抓 → 完整性驗證 → Stage 0~3**

Trading Calendar 是資料抓取的上游基準，不使用 `pandas.bdate_range()` 判定台股應有交易日。

## 10 項 Production 保護

1. **增量更新**：只抓新增或缺失的交易日。
2. **缺日自動補抓**：Cache 缺交易日，依 Calendar 計算 missing dates 後自動向 FinMind 補抓。
3. **Trading Calendar**：使用 `TaiwanStockTradingDate`，本地保存 `cache/reference/trading_calendar.json`。
4. **K0/K1/K2 完整性**：Stage 2 必須驗證 K0/K1/K2 是 Calendar 定義的最近三個交易日。
5. **MA20/MA60 歷史完整性**：Stage 1 使用最近 61 個有效交易日；缺日先修復，修復失敗為 UNKNOWN。
6. **Duplicate Date**：同一 cache 檔案重複日期直接拒絕；跨檔同日資料若 OHLC/Volume 衝突則 `DATA_CONFLICT`。
7. **OHLC 合法性**：檢查 OHLC 關係、數值完整性與非負成交量。
8. **API 空資料/錯誤**：`FETCH_EMPTY`、timeout/error 與資料格式錯誤不視為休市日。
9. **Atomic Cache**：資料驗證後先寫 `.tmp`，再 atomic rename。
10. **Data Freshness Manifest**：`cache/data_freshness.json` 保存 calendar、refresh、repair、provider stats。

## 資料需求

- Stage 1：最新完成交易日往前 **61 個交易日**。
- Stage 2：最新完成交易日的 **K0/K1/K2**。
- Stage 3：至少 **K0~K4** 所需的 5 個交易日。

目前 Runner 在 Stage 0 PASS 後會先確保 Stage 1 所需的 61 根日 K，再進 Stage 1~3。

## Fail-Closed

如果自動補抓後仍缺必要日期，不使用更舊的 K 棒代替，不進行錯誤的 3K PASS；Stage 會標記 UNKNOWN / DATA INTEGRITY failure。

## 來源

Trading Calendar 使用 FinMind `TaiwanStockTradingDate`。該資料集提供台股交易日清單，並可作為日期需求的上游基準。
