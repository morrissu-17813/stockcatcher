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


## v1.2.11 影子驗證（離線唯讀）

本版新增獨立的歷史訊號整理工具，不會啟動 Production Runner、不呼叫行情 API、不發送 Telegram，也不修改 Stage 0～3 選股條件。

從 `stockcatcher/` 專案根目錄執行：

```powershell
python -X utf8 -m tianji_3k.validation.shadow_validation `
  --prediction-root .\tianji_3k\predictions `
  --validation-root .\tianji_3k\validation `
  --signal-xlsx ".\tianji_3k\research_inputs\天機3K_2026-10-14_22筆訊號品質比較表.xlsx" `
  --output-dir .\tianji_3k\shadow_reports\2026-11-05
```

輸出包含 CSV、JSON 資料集及 JSON 摘要。每次請使用新的輸出資料夾；若資料夾已存在且非空，程式會拒絕覆寫。歷史 Excel 的代理報酬不是實際成交損益，且不得與 T+5/T+15/T+30 里程碑報酬混為一談。缺少的里程碑一律保留 `UNKNOWN`。

### 完整套件內容

本發行包包含完整 `tianji_3k/` 原始碼、測試、文件、設定範本及本次基準包中既有的 Prediction/Validation 歷史紀錄；不包含 Python 編譯快取、pytest 快取、虛擬環境及可重建的行情快取。請先備份本機資料夾，再以本包的 `tianji_3k/` 完整資料夾替換原資料夾。不要刪除你本機後續新增、且未包含在本次基準包中的紀錄。
