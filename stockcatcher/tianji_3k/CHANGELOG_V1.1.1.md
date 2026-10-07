# Tianji 3K Production v1.1.1

## 2026-10-07 Telegram 通知排版優化

本版只調整 Telegram INTRADAY_3K_PREDICTION 呈現，不修改交易策略與判斷門檻。

### 1. nStock 可點擊個股連結
- 股號＋股名改為 Telegram HTML 超連結。
- 連結格式：`https://www.nstock.tw/{symbol}`。

### 2. 數值排版
- 現價、漲幅、突破基準統一顯示至小數點 1 位。
- 預估量維持整數張並加入千分位。
- 預估量比改為 1 位小數並附 `x`，例如 `4.5x`。
- `有效突破 True/False` 改為 `是/否`。

### 3. 訊息結構
- 標題 → 個股連結 → 價格/漲幅 → 突破 → 量能 → Ground Truth 提醒。
- 關閉 Telegram 網頁預覽，避免 nStock 連結造成訊息大卡片。

### 4. 驗證
- pytest：112 passed / 0 failed。
- 新增 Telegram 排版與 nStock 連結測試。
