# 天機 3K Stage 0 Production V3

V3 將 Stage 0 從單純 Audit 升級為可供 Runner 使用的資料層：

- 現有 StockUniverseProvider
- `tianji_3k/cache/daily/*.json`
- TWSE OpenAPI：上市日行情、基金基本資料、權證基本資料、暫停交易、處置
- TPEx OpenAPI：上櫃行情、權證、開放式基金、暫停/恢復、處置、變更交易/管理/停止交易
- 官方參照資料快取 6 小時，避免每次執行重打 API
- 任一必要官方來源失敗時，對應分類保持 UNKNOWN，不會猜成 PASS

## 執行

```powershell
python -m tianji_3k.tools.stage0_production --refresh-reference `
  --volume-threshold 1000 `
  --csv tianji_3k\cache\stage0_production.csv `
  --json tianji_3k\cache\stage0_production.json
```

平常執行不需要 `--refresh-reference`，會使用 6 小時 reference cache。

若要查看官方 API 錯誤：

```powershell
python -m tianji_3k.tools.stage0_production --show-reference-errors
```

## 安全規則

1. `None` / 缺資料不等於 0。
2. UNKNOWN 不等於 PASS。
3. Product Type 只在官方參照集或明確可信欄位支持時通過。
4. Trading Status 只在對應市場的必要狀態來源全部成功時才可判定 NORMAL。
5. 成交量只信任現有 daily cache；沒有 cache 就是 VOLUME_UNKNOWN。
6. 不呼叫 FinMind。
7. 不讀取或輸出 `.env` / token / API secret。
