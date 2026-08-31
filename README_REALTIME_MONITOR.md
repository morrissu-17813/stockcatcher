# 🚀 權證現股即時逆向監控系統 - 快速啟動指南

## 📋 已完成集成

### ✅ 1. nstock 超連結
- Telegram 通知中包含可點擊的 nstock 超連結
- 格式: `[股票代號](https://www.nstock.tw/stock_info?stock_id=XXXX)`
- 用戶可直接點擊查看走勢圖

### ✅ 2. FinMind API 內部人資料
- 使用 `FINMIND_TOKEN` 從 FinMind 官方 API 查詢真實內部人買超
- Dataset: `TaiwanStockInsiderTrading`
- 自動替代壞掉的 TWSE 內部人 API
- 優先級: 內部人買超 > 三大法人 > 融資

### ✅ 3. Tier 優先級邏輯（累積式）
```
🟡 Tier 1 基礎觸發
   └─ 量能 ≥ 2.5x + 技術分數 ≥ 60 + 日線多頭型態
      
🟠 Tier 2 進階觸發
   └─ Tier1 + 內部人買超存在
      
🔴 Tier 3 終極觸發
   └─ Tier2 + 大戶買超 ≥ 400張 + 連買 ≥ 3天
```

### ✅ 4. 定時執行 Loop（每 10 秒）
- 盤中時間監控: 09:00 ~ 13:30
- 盤外自動暫停
- 每 5 分鐘刷新現股池
- 實時 MIS 逆向掃描

---

## 🎯 使用方式

### 方式 1: 直接執行（最簡單）

```bash
cd c:\Users\m2994\Desktop\stockcatcher\stockcatcher
python technical_indicator_engine.py
```

**效果:**
- 🔄 每 10 秒掃一次現股急拉信號
- 🎯 自動檢測觸發條件
- 📱 符合條件自動發 Telegram
- ⏰ 盤中 09:00-13:30 自動運行
- 🛑 Ctrl+C 停止監控

---

### 方式 2: 集成到現有 scanner.py

在 `scanner.py` 中導入並調用:

```python
from technical_indicator_engine import WarrantTelegramAlertRunner

runner = WarrantTelegramAlertRunner(quota=30, chat_id="-1003613268841")
alerts = runner.run_cycle()  # 執行一輪掃描
```

---

### 方式 3: 在 cron / 任務排程中定時執行

**Windows 排程任務:**
```
工作名稱: 權證即時監控
程式: C:\Users\m2994\Desktop\stockcatcher\.venv\Scripts\python.exe
引數: C:\Users\m2994\Desktop\stockcatcher\stockcatcher\technical_indicator_engine.py
觸發程序: 每天 08:50 啟動
停止於: 13:40 停止
```

---

## 📊 通知訊息範例

```
🔴 Tier 3 終極觸發 (加大戶+連買)

📈 標的：[2330](https://www.nstock.tw/stock_info?stock_id=2330)
💰 價格: 905.20
🎯 觸發原因: 量能2.50x + 技術65.0 + 內部人連買 + 大戶500張

─────────
📊 技術面:
  RSI14: 65.0
  技術分數: 70.0
  趨勢: 超強偏多
  突破: 3K=True, 5K=False
  量能比: 2.50x

─────────
💼 籌碼面:
  內部買超: 2000 (連三買)
  大戶融資: 500
  外資: 250
  投信: 180
  自營: 90

═════════════════════
反查標的: 2330
MIS急拉量: 50000000
先行價差: 905.20
籌碼來源: 內部人買超(3位)
```

---

## ⚙️ 環境變數（已設置）

```
.env 中已有:
  FUGLE_API_KEY          ✓ 富果免費 API
  FINMIND_TOKEN          ✓ FinMind JWT Token
  TELEGRAM_BOT_TOKEN     ✓ Telegram Bot Token
  TELEGRAM_CHAT_ID       ✓ 目標群組
```

確認無誤:
```bash
cd c:\Users\m2994\Desktop\stockcatcher
python -c "import os; from dotenv import load_dotenv; load_dotenv('.env'); print('✓ FINMIND_TOKEN:', 'Yes' if os.getenv('FINMIND_TOKEN') else 'No')"
```

---

## 🔧 可調參數

在 `WarrantTelegramAlertRunner` 中修改:

```python
runner = WarrantTelegramAlertRunner(
    quota=30,           # 現股池大小（檔數）
    group_size=20,      # 每組掃描股票數
    chat_id="-1003613268841"  # Telegram 群組
)
```

在 `main loop` 中調整:
```python
time.sleep(10)  # 掃描間隔（秒）
```

---

## ⏰ 監控時間表

| 時間 | 狀態 |
|------|------|
| 08:50 ~ 09:00 | 準備階段（載入數據） |
| **09:00 ~ 13:30** | **⚡ 主動監控（每10秒掃描）** |
| 13:30 ~ 08:50 | 待機（每60秒檢查一次時間） |

---

## 📈 預期效果

✅ **即時性**: 盤中 10 秒內偵測現股急拉  
✅ **準確性**: 3 層累積式優先級判斷  
✅ **覆蓋性**: 30 檔熱門現股自動監控  
✅ **通知性**: Telegram 主動推送 + nstock 超連結  
✅ **數據源**: 真實內部人 + 法人 + 融資資料  

---

## 🐛 常見問題

**Q: 為什麼沒有收到通知？**  
A: 檢查:
1. 盤中時間是否在 09:00-13:30
2. Telegram token/chat_id 是否正確
3. 搜尋結果是否符合 3 層觸發條件

**Q: FinMind API 返回為空？**  
A: 正常。FinMind 會在盤後更新內部人資料。系統已備有 TWSE fallback。

**Q: 怎樣停止監控？**  
A: 按 `Ctrl+C`，系統會正常退出

**Q: 怎樣修改掃描間隔？**  
A: 在 `main` 函數最後的 `time.sleep(10)` 修改秒數

---

## 📞 測試指令

### 快速整合測試
```bash
python test_full_integration.py
```

### 測試優先級邏輯
```bash
python test_priority_logic.py
```

### 測試 FinMind API
```bash
python -c "from stockcatcher.technical_indicator_engine import FundamentalChipDataLayer; data = FundamentalChipDataLayer.fetch_insider_buy_data(5); print(f'查詢: {len(data)} 檔內部人買超')"
```

---

**🎉 系統已就緒，可開始盤中監控！**
