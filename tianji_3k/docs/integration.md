# StockCatcher Integration

本模組位於既有專案：

`stockcatcher/tianji_3k/`

請不要在此目錄新增 `.env`。程式會由 `data/config.py` 嘗試讀取上層專案根目錄的 `.env`。

下一階段：
1. 對接既有 Fugle provider
2. 對接既有 MIS provider
3. 對接既有資料標準
4. 將真實盤中 5 分 K / 量比資料接入
5. 完成 Stage 3 預判
6. 建立 Telegram 通知格式
7. 建立收盤驗證與命中率統計
