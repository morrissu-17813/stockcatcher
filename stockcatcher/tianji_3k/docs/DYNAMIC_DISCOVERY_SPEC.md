# 天機 3K — Dynamic Discovery Spec

## 目的

Dynamic Discovery 是**盤中獨立層**，不修改、不取代盤前 3K Core（Stage 0~3）。
它的工作只有一件事：從全市場盤中行情中，持續找出「現在開始具備 3K 突破潛力」的股票，補進 Intraday Radar。

## 正式資料流

```text
全市場 MIS Snapshot
        ↓
Dynamic Discovery Gate
        ↓
有限量歷史日K補充（Cache-first / FinMind）
        ↓
Dynamic 3K History Ready
        ↓
Intraday State Machine
        ↓
Fugle 5分鐘K微觀確認
        ↓
Projected Volume >= 1.5x
        ↓
INTRADAY_3K_PREDICTION
        ↓
Telegram
```

## 1. Discovery Universe

只掃描一般普通股：

- 上市 TWSE
- 上櫃 TPEx
- 昨日成交量 >= 1,000 張
- 排除 ETF / 非一般股票 / 興櫃 / 處置或不正常標的

Universe metadata 由現有 `StockUniverseProvider` 建立並快取，不在每個 Radar cycle 重抓。

## 2. MIS Dynamic Gate

每個 Radar cycle 使用全市場 MIS snapshot，**不對每檔股票逐一呼叫 FinMind/Fugle**。

候選條件：

- 今日漲幅 >= 3%
- 現價 > 今日開盤價
- 今日累積成交量 >= 300 張
- 昨日成交量 >= 1,000 張
- 今日成交量 pace >= 昨日全天量的 0.8 倍（按當日 09:00~13:30 已經過時間正規化）

這些是「發現候選」條件，不是 3K Core PASS。

## 3. Historical 3K Background

只有通過 Dynamic Gate 的少數候選才補歷史資料。

- Cache-first
- 需要至少 61 根有效日K
- Stage 1 趨勢沿用正式 Production 定義：
  - Close > MA20
  - Close > MA60
  - MA20 > MA60
  - MA20 上升
- 建立 T 日盤中突破基準：
  - T-1 High
  - T-2 High
  - `breakout_level = max(T-1 High, T-2 High)`
- 建立 5 日平均成交量 baseline
- 5日均量 < 1,000 張者，不進 Dynamic Radar

**Dynamic Candidate 不宣稱 Stage 0/2/3 PASS。**

## 4. Intraday Confirmation

進入 Radar 後，沿用既有 State Machine：

- 現價必須站在今日開盤價之上
- 漲幅 >= 4%
- 有效突破 `breakout_level * 1.003`
- 需要兩個不同 MIS data identity 的連續確認

通過後才呼叫 Fugle 5m。

## 5. Fugle 5m Confirmation

只在真正接近/觸發突破時呼叫：

- 使用已完成的 5 分K
- 最近 3 根形成微觀突破判定
- 第 3 根 Close > 前兩根 High 最大值
- 第 3 根成交量 / 前 20 根基準平均 >= 1.2x

這是微觀確認層，不取代 Production Projected Volume。

## 6. Projected Volume

Prediction 的正式硬門檻維持：

`projected_volume_ratio >= 1.5x`

不足時只寫 audit/rejection event，不建立正式 `INTRADAY_3K_PREDICTION`。

## 7. API Data Source

### A. MIS — Primary Discovery

目前 Production 使用 TWSE MIS market-wide batch snapshot。
用途：

- 現價
- 昨收
- 今日開盤
- 今日累積成交量
- 漲幅
- data identity / timestamp

### B. StockUniverseProvider — Universe Metadata

用途：

- 股票代號/名稱
- TWSE / TPEx
- 昨日成交量
- 股票池過濾

### C. FinMind — Selective Historical Enrichment

用途：

- Dynamic Candidate 缺少歷史 cache 時補 61 根以上日K
- 不得對全市場每輪呼叫
- 共用 Production rolling request budget

### D. Fugle Intraday Candles — Breakout Confirmation

Endpoint：
`GET /marketdata/v1.0/stock/intraday/candles/{symbol}?timeframe=5`

用途：

- 已完成 5 分K
- 微觀突破
- 5m volume confirmation

### E. Fugle Historical — Ground Truth / fallback

用途：收盤驗證或既有 Ground Truth 流程；不作為每 20 秒的市場掃描來源。

## 8. API Load Policy

```text
每一 Radar cycle
    ↓
MIS 全市場 snapshot
    ↓
Dynamic Gate
    ↓
最多 3 檔新的歷史 enrichment
    ↓
只有 State Machine 真正觸發的股票
    ↓
Fugle 5m
```

因此不能出現：

```text
全市場 600+ 檔
× 每20秒
× FinMind
× Fugle 5m
```

## 9. 重要邊界

Dynamic Discovery 不加入：

- 週KD黃金交叉
- 日KD黃金交叉
- SMC 金蛋蛋
- 2TON
- 權證主力
- 其他歷史版本條件

除非未來另行確認並修改本 Spec。
