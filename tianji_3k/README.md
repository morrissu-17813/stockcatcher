# Tianji 3K V1.0

天機 3K 盤中預判引擎第一版骨架。

## 目錄
- docs/: 策略與系統規格
- skills/: Python 開發規範
- core/: Stage 0~3 核心流程
- strategy/: 3K 策略條件與評分
- data/: 資料介接與標準化
- validation/: 收盤驗證
- notification/: Telegram 通知
- models/: 統一資料模型
- tests/: 單元與整合測試

## 環境
本模組預設共用上層 `stockcatcher/.env`，不建立自己的 `.env`。

## 啟動
從 `stockcatcher/` 專案根目錄執行：

```bash
python -m tianji_3k
```

目前 V1.0 以「可測試骨架」為主；實際 MIS/Fugle API 欄位請依既有 StockCatcher 實作接入。
