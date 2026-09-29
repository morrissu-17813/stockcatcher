# 天機 3K — Stage 0 Audit V2

用途：在不呼叫 FinMind 的前提下，使用現有 Universe 與 `tianji_3k/cache/daily`，逐層模擬 Stage 0。

## 核心原則

1. 固定排除順序：商品類型 → 市場 → 交易狀態 → 資料品質 → 最近可得交易日成交量。
2. 每檔股票只記錄第一個淘汰／未驗證原因。
3. `UNKNOWN` 絕不視為 PASS。
4. Cache 缺成交量時，預設不回退到 Universe 的 `previous_volume_lots`。
5. 因目前部分 Universe provider 可能把缺失成交量轉成 `0.0`，V2 會把這類值視為 UNKNOWN，而不是 0 張。
6. 成交量一律保留 shares 與 lots；`lots = shares / 1000`。
7. 不使用 FinMind，因此不會消耗 FinMind API 額度。
8. 不讀取或輸出 `.env`、token、API key。

## 基本執行

在 `stockcatcher` repo root：

```powershell
python -m tianji_3k.tools.stage0_audit --volume-threshold 1000
```

輸出 CSV + JSON：

```powershell
python -m tianji_3k.tools.stage0_audit `
  --volume-threshold 1000 `
  --csv tianji_3k\cache\stage0_audit.csv `
  --json tianji_3k\cache\stage0_audit.json
```

## Universe 欄位信任

預設不信任僅由 `security_type=common_stock` 宣告的商品類型：

```text
Trust Universe fields : False
```

若已確認目前 Universe 的商品／狀態欄位是可靠外部來源，可明確使用：

```powershell
--trust-universe-fields
```

## 成交量回退

預設：Cache 找不到成交量 → `VOLUME UNKNOWN` / `DATA_QUALITY`，不會把缺值當 0。

若你確定 Universe 的 `previous_volume_lots` 可信，才開啟：

```powershell
--allow-universe-volume-fallback
```

即使開啟，`0.0` 仍不會被當成有效成交量，避免目前 provider 將 API 缺值轉成 0.0 的問題。

## 逐檔輸出欄位

CSV / JSON rows 包含：

- `symbol`
- `name`
- `market`
- `product_type`
- `product_source`
- `status`
- `status_source`
- `latest_cache_date`
- `volume_shares`
- `volume_lots`
- `volume_source`
- `first_exclusion`
- `first_exclusion_detail`
- `final_stage0_pass`

## 測試

```powershell
python -m pytest tianji_3k\tests\test_stage0_audit.py -q
python -m compileall -q tianji_3k
```

V2 測試涵蓋：

- 固定 Stage 0 排除順序
- 1000 張門檻
- 多日期 Cache 取最新資料
- Cache 缺值不再誤判 0 張
- 商品類型 UNKNOWN 不得 PASS
- 交易狀態 UNKNOWN 不得 PASS
- 自訂成交量門檻
