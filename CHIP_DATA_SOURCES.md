# 台股籌碼資料來源完整指南

## 📊 優先級：內部人 > 三大法人 > 融資

### 1️⃣ **內部人買超資料** (最重要，但需要特殊手段)

| 來源 | 方式 | 免費額度 | 格式 | 推薦度 |
|------|------|--------|------|--------|
| **MOPS 公開資訊觀測站** | 網頁抓取 | 無限制 | HTML | ⭐⭐⭐⭐⭐ |
| **FinMind API** | REST API | 有限免費 | JSON | ⭐⭐⭐⭐ |
| **CMoney API** | REST API | 付費 | JSON | ⭐⭐⭐⭐ |
| **Moneybar API** | REST API | 免費 | JSON | ⭐⭐⭐ |

**推薦方案**: FinMind 免費方案 (1000 次/月)

```bash
pip install finmind
# 需要註冊帳號，免費方案無需 API key
```

---

### 2️⃣ **三大法人買超資料** (穩定，TWSE API 可用)

| 來源 | 端點 | 免費額度 | 更新頻率 |
|------|------|--------|--------|
| **TWSE 每日三大法人** | `/v1/opendata/t187ap40_L` | 無限制 | 每日 |
| **Fugle API** | `/stock/intraday/quote/{symbol}` | 有限免費 | 即時 |
| **FinMind** | `get_institutional_investors` | 1000次/月 | 每日 |

**實際可用 API 端點**:
```
https://www.twse.com.tw/en/page/trading/fund/T03.html
# 可直接下載 CSV，或解析表格
```

---

### 3️⃣ **融資買超資料** (較不重要，但易取得)

| 來源 | 方式 | 免費 |
|------|------|-----|
| **TWSE 融資融券** | CSV 下載 | ✓ |
| **Fugle API** | 即時行情 | ✓ |

---

## 🔧 **目前實作狀態**

### ✅ 已整合
- 量能 2.5x 檢測 (MIS API)
- 技術面評分 (自有引擎)
- 30 檔現股池 (TWSE 權證資料)

### ❌ 需要補充
- 內部人買超：HTML 解析或 FinMind
- 三大法人：TWSE CSV 下載或 Fugle

---

## 📌 **推薦整合方案**

### 選項 A：完全免費 (延遲 1-2 天)
1. 每日 1 次抓取 TWSE CSV
2. 解析存入 SQLite
3. 查詢時從 DB 讀取

### 選項 B：半免費 (即時性好，但受限)
1. FinMind 免費方案：內部人 + 三大法人
2. Fugle：量能 + 即時報價
3. 自有引擎：技術面

### 選項 C：完整方案 (需一次性投資)
1. 訂閱 CMoney/TEJ 完整籌碼資料
2. 每分鐘更新一次
3. 支援複雜篩選

---

## 🚀 **推薦你立即做：**

1. **註冊 FinMind**
   ```python
   from finmind.data import DataLoader
   loader = DataLoader()
   # 獲取內部人買超
   df = loader.data_getter("TaiwanStockInsiderTrade", stock_id="2330", date="20240101")
   ```

2. **每日定時任務**
   ```python
   # 每日 15:00 後抓 TWSE CSV
   # 解析三大法人 + 融資買超
   # 存入 DB
   ```

3. **整合進現有系統**
   ```python
   # 修改 FundamentalChipDataLayer
   # 優先查 DB，無則用推估
   ```

---

## 📋 **現在你有 3 個選擇**

### 立即可用版（使用現有量能推估）
已整合進 `WarrantTelegramAlertRunner`，效果 70%

### 準基礎版（+TWSE CSV）
需要 10 分鐘手動整合

### 完整版（+FinMind）
需要註冊，但完全真實

---

**你想要我幫你做哪一個？**
