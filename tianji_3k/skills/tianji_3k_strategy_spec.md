# 天機 3K 策略規格書
# tianji_3k_strategy_spec.md

版本：V1.0  
狀態：LOCKED / Strategy Specification  
用途：作為「天機 3K 盤中預測引擎」的策略唯一規格來源（Single Source of Truth）

---

## 0. 文件定位

本文件只定義「天機 3K」策略的數學、交易邏輯、狀態機、訊號、驗證與資料定義。

本文件不負責：
- Python 程式架構
- API client 實作
- Telegram SDK
- Supabase
- asyncio
- pytest
- Ruff
- 部署方式

上述工程規範由另一份文件：
`tianji_3k_python_skill.md`
負責。

### 最高原則

1. V2.4 生產版保持不變。
2. V1.0 是獨立的新引擎。
3. V2.4 只能作為已驗證經驗與資料來源設計參考，不得被 V1.0 runtime 依賴。
4. 任何「盤中預測」都不能冒充「已完成 3K」。
5. 真正的 3K PASS 必須以收盤後完成的日 K 線 Ground Truth 判定。
6. 所有策略規則必須避免 Look-ahead Bias。
7. 未經實證驗證的分數不得直接稱為機率。

---

# 1. 天機 3K 的最終目的

核心問題：

> 在交易時間內，提前找出「今天收盤後高度可能形成 3K」的股票。

而不是：

> 等收盤後才找出今天已經形成 3K 的股票。

因此策略分成兩層：

### A. Daily 3K Ground Truth

收盤後判定今天是否真的完成 3K。

### B. Intraday 3K Prediction

盤中使用當下已知資料，預測今天收盤是否可能完成 3K。

---

# 2. Canonical 3K 定義

V1.0 的 3K 基礎條件由三個 Stage 組成：

```text
Stage 0：股票資格／流動性
        ↓
Stage 1：趨勢
        ↓
Stage 2：突破
        ↓
Stage 3：量能
        ↓
3K PASS
```

其中：

- Stage 0 = Universe Eligibility
- Stage 1 = Trend
- Stage 2 = Breakout
- Stage 3 = Volume Confirmation

Stage 0–3 都 PASS，才稱：

`3K PASS`

---

# 3. Stage 0：股票池與資格篩選

## 3.1 市場範圍

只保留：

- TWSE 上市普通股
- TPEx 上櫃普通股

排除：

- 興櫃
- ETF
- ETN
- 權證
- 特別股
- 債券
- 存託憑證
- 其他非普通股商品

## 3.2 交易狀態排除

排除：

- 處置股
- 停牌
- 暫停交易
- 非正常交易狀態
- 明顯資料異常商品

## 3.3 流動性粗篩

若昨日成交量可低成本取得：

```text
昨日成交量 < 500 張
→ 排除
```

500 張 = 500 lots。

若取得昨日成交量需要約 1,800 次額外 API request：

> 不得為了 Stage 0 的 500 張粗篩而浪費大量 API quota。

此時應優先完成：
- 商品類型
- 市場
- 交易狀態
- 資料品質

再進入歷史資料 FULL_SCAN。

## 3.4 Stage 0 排除順序

固定：

```text
Product Type
→ Market
→ Disposal / Suspended / Status
→ Data Quality
→ Yesterday Volume
→ FULL_SCAN
```

## 3.5 Stage 0 輸出

每檔股票至少保留：

```text
symbol
name
exchange
market
industry
security_type
trading_status

is_etf
is_etn
is_warrant
is_preferred_stock
is_bond
is_dr
is_disposal
is_suspended

previous_volume
previous_volume_lots

pre_filter_pass
exclude_reason
```

---

# 4. Stage 1：趨勢條件

## 4.1 目的

Stage 1 只回答：

> 股票是否處於有利的中短期上升趨勢？

Stage 1 不判斷突破，不判斷量能。

## 4.2 使用資料

使用最新「已完成交易日」的日 K：

```text
K0 = 最新已完成交易日
K1 = K0 前一交易日
K2 = K0 前兩交易日
```

禁止直接使用尚未完成的今日 K 作為 Stage 1 Ground Truth。

## 4.3 硬條件

以下全部必須成立：

```text
Close(K0) > MA20(K0)

Close(K0) > MA60(K0)

MA20(K0) > MA60(K0)

MA20(K0) > MA20(K1)
```

也就是：

```text
收盤價 > 20MA
收盤價 > 60MA
20MA > 60MA
20MA 向上
```

## 4.4 輔助指標

可計算：

```text
MA20 slope %
Close vs MA20 %
Close vs MA60 %
Trading days
```

這些數值可以用於：
- 排序
- 訊號品質
- 日後統計

但 V1.0 不得擅自把輔助條件改成硬篩選。

## 4.5 MA 計算

以 Python 計算：

```text
MA20 = rolling mean of Close over 20 trading days
MA60 = rolling mean of Close over 60 trading days
```

不依賴額外技術指標 API。

---

# 5. Stage 2：突破條件

## 5.1 目的

Stage 2 只判斷：

> 最新完成日 K 是否完成有效突破？

不加入成交量條件。

## 5.2 K 棒定義

```text
K0 = 最新完成交易日
K1 = 前一交易日
K2 = 前兩交易日
```

## 5.3 硬條件

### 條件 1：K0 必須是紅 K

```text
Close(K0) > Open(K0)
```

### 條件 2：K0 漲幅至少 4%

```text
gain_pct =
(Close(K0) / Close(K1) - 1) * 100

gain_pct >= 4.0
```

### 條件 3：K0 High 突破 K1 High

```text
High(K0) > High(K1)
```

### 條件 4：K0 High 突破 K2 High

```text
High(K0) > High(K2)
```

### 條件 5：K0 Close 必須站上突破位

```text
breakout_level =
max(High(K1), High(K2))

Close(K0) > breakout_level
```

## 5.4 Stage 2 PASS

必須全部成立：

```text
Bullish K
AND
Gain >= 4%
AND
High > K1 High
AND
High > K2 High
AND
Close > breakout_level
```

## 5.5 Stage 2 輔助資料

保存：

```text
breakout_level
intraday_breakout_pct
close_breakout_pct
```

其中：

```text
intraday_breakout_pct =
High(K0) / breakout_level - 1

close_breakout_pct =
Close(K0) / breakout_level - 1
```

## 5.6 特殊漲停規則

V1.0：

> 不提供特殊漲停放寬條件。

漲停不代表自動突破 PASS。

仍然必須按照 Stage 2 的正式定義判斷。

---

# 6. Stage 3：量能條件

## 6.1 目的

Stage 3 只回答：

> 突破是否有足夠成交量支持？

## 6.2 硬條件

### 條件 1：5 日平均成交量至少 1,000 張

```text
VMA5 >= 1,000 lots
```

### 條件 2：今日成交量 > 昨日成交量

```text
Today Volume > Yesterday Volume
```

### 條件 3：今日成交量至少為 5 日均量 1.5 倍

```text
Today Volume / VMA5 >= 1.5
```

三者全部成立才：

`Stage 3 PASS`

## 6.3 成交量單位

Fugle / FinMind 歷史資料通常以股數表示。

策略層統一：

```text
volume_shares
volume_lots

volume_lots = volume_shares / 1000
```

禁止在策略不同模組混用「股」與「張」。

---

# 7. Daily Context

盤中預測不能每 20 秒重新完整執行 Stage 0–3。

FULL_SCAN 後建立：

`Daily Context`

範例：

```python
{
    "prev_close": 120.0,
    "k1_high": 125.0,
    "k2_high": 123.0,
    "breakout_level": 125.0,
    "vma5": 8000,
    "yesterday_volume": 10000,
    "ma20": 115.0,
    "ma60": 108.0,
}
```

Daily Context 的意義：

> 把「盤前已知的歷史結構」固定下來，盤中只更新即時資料。

這可以避免：
- 重複 API request
- 策略基準漂移
- Look-ahead Bias
- 每 20 秒重算歷史資料

---

# 8. FULL_SCAN 時間

V1.0：

```text
FULL_SCAN = 08:20
```

只在交易日執行。

流程：

```text
08:20
 ↓
Stage 0
 ↓
Stage 1
 ↓
Stage 2
 ↓
Stage 3
 ↓
建立 Preselected Pool
 ↓
建立 Daily Context
 ↓
等待 09:00
```

---

# 9. 盤中 MIS Radar

## 9.1 更新頻率

```text
每 20 秒
```

MIS 用途：

> 全市場快速 Radar。

## 9.2 盤中核心資料

至少：

```text
symbol
current_price
previous_close
today_open
cumulative_volume
up_pct
is_traded
```

## 9.3 資料角色

```text
MIS = Broad Fast Radar
```

而不是把所有股票都交給昂貴的深度 API。

---

# 10. 盤中 3K 預測條件

## 10.1 核心問題

盤中每次 snapshot 都要回答：

> 如果現在的狀態延續到收盤，這檔股票是否高度可能完成 3K？

## 10.2 價格條件

以下為正式盤中價格條件：

```text
current_price > K1 High

current_price > K2 High

current_price / previous_close - 1 >= 4%

current_price > today_open
```

其中：

```text
breakout_level =
max(K1 High, K2 High)
```

## 10.3 有效突破

單純碰到突破位不算有效。

正式定義：

```text
current_price >= breakout_level * 1.003
```

也就是：

```text
突破幅度 >= 0.3%
```

並且：

```text
連續 2 個有效 snapshot
```

兩次 snapshot 必須具有不同的有效資料身份。

如果 API 回傳完全相同的資料：

> 不得把同一筆資料重複計算成兩次確認。

若 provider 有 timestamp / sequence / quote identity，優先使用。

---

# 11. 盤中成交量預估

## 11.1 V1.0 Baseline

交易時間：

```text
09:00–13:30
```

總交易分鐘：

```text
270 minutes
```

定義：

```text
elapsed_minutes =
09:00 到目前時間的實際交易分鐘
```

基準公式：

```text
estimated_eod_volume =
current_cumulative_volume
×
270 / elapsed_minutes
```

## 11.2 兩個重要比例

```text
estimated_vs_yesterday =
estimated_eod_volume / yesterday_volume

estimated_vs_vma5 =
estimated_eod_volume / vma5
```

## 11.3 注意

這是：

`Baseline Projection`

不是：

`Guaranteed Volume`

因為真實盤中成交量通常具有時間分布、開盤集中、午盤衰減等特徵。

V1.0 先用線性估算收集資料。

未來使用歷史事件 log 建立：

`Time-of-Day Volume Curve`

---

# 12. 早盤保護

## 12.1 09:00–09:05

線性成交量預估非常不穩定。

因此：

> 早盤可以偵測價格突破，但不能只靠 09:00–09:05 的線性量能預估直接宣稱最高信心。

## 12.2 原則

```text
Price breakout
可以早發現

Volume confidence
需要隨時間增加可信度
```

---

# 13. Intraday State Machine

正式狀態：

```text
WATCH
APPROACHING
BREAKOUT
PRE_3K
HIGH_CONFIDENCE
BREAKOUT_LOST
SECOND_BREAKOUT
CLOSED
```

---

# 14. State 定義

## 14.1 WATCH

尚未接近有效突破。

## 14.2 APPROACHING

接近突破位。

V1.0 建議：

```text
距 breakout_level <= 0.5%
```

這是內部狀態。

預設不發 Telegram。

## 14.3 BREAKOUT

條件：

```text
price > K1 High
price > K2 High
gain >= 4%
effective breakout >= 0.3%
2 consecutive valid snapshots
```

進入：

`BREAKOUT`

並可發送一次 🚀。

## 14.4 PRE_3K

條件：

```text
BREAKOUT 成立

AND
estimated_eod_volume / VMA5 >= 1.5

AND
estimated_eod_volume >= yesterday_volume

AND
breakout continues to hold
```

發送一次：

`🔥 PRE_3K`

注意：

`PRE_3K ≠ 3K PASS`

它只是盤中高機率結構。

## 14.5 HIGH_CONFIDENCE

條件：

```text
PRE_3K

AND
estimated_vs_vma5 >= 1.8

AND
breakout_pct >= 0.5%

AND
至少 3 個有效 snapshot 持續站上 breakout_level
```

發送一次：

`🔥🔥 HIGH_CONFIDENCE`

---

# 15. BREAKOUT_LOST

## 15.1 定義

突破後若回落至：

```text
price < breakout_level * 0.997
```

並且：

```text
連續 2 個有效 snapshot
```

才視為：

`BREAKOUT_LOST`

## 15.2 設計目的

避免：

- 單一 tick 下跌
- API 噪音
- 正常震盪

造成假突破失效。

## 15.3 通知

V1.0：

`BREAKOUT_LOST` 主要進入 log。

預設不發 Telegram。

---

# 16. SECOND_BREAKOUT

當：

```text
BREAKOUT_LOST
→
重新滿足有效突破
```

則：

`SECOND_BREAKOUT`

可以發送一次重大重新突破通知。

避免同一檔股票：

```text
突破
跌破
突破
跌破
突破
...
```

造成通知洗版。

---

# 17. Score System

V1.0 使用：

`Condition Completion Score`

不是機率。

## 17.1 分數

| 條件 | 分數 |
|---|---:|
| 突破 K1/K2 | +25 |
| 漲幅 >= 4% | +15 |
| 有效突破 >= 0.3% | +10 |
| 預估量 >= 1.5 × VMA5 | +15 |
| 預估量 >= 昨日量 | +15 |
| 預估量 >= 1.8 × VMA5 | +10 |
| 突破持續性 | +10 |
| **最大** | **100** |

## 17.2 分數區間

```text
0–39   WATCH
40–59  APPROACHING
60–74  BREAKOUT
75–89  PRE_3K
90–100 HIGH_CONFIDENCE
```

## 17.3 嚴格限制

不能寫：

```text
Score 90 = 90% 機率
```

正確說法：

```text
Score 90 = 條件完成度高
```

未來只有在大量 Ground Truth 資料校準後，才可以建立：

```text
Score → empirical probability
```

---

# 18. PRESELECTED 與 INTRADAY DISCOVERY

V1.0 有兩條進場路徑。

## 18.1 PRESELECTED

已在 08:20 通過：

```text
Stage 0
Stage 1
Stage 2
Stage 3
```

的股票。

這些股票優先監控。

## 18.2 INTRADAY_DISCOVERY

08:20 沒進入 Preselected Pool，但盤中自行形成強勢結構。

可以進入盤中 Discovery。

## 18.3 重要原則

Preselected 股票：

> 盤中不需要每 20 秒重新跑完整 Stage 0–3。

使用：

```text
Daily Context
+
Live Snapshot
```

即可。

---

# 19. Telegram 通知

## 19.1 V1.0 第一階段

只使用：

`Telegram`

暫不加入 LINE。

## 19.2 通知層級

### 🚀 BREAKOUT

代表：
- 已有效突破
- 2 個有效 snapshot

### 🔥 PRE_3K

代表：
- 突破
- 4% 漲幅
- 預估量能達標
- 突破仍維持

### 🔥🔥 HIGH_CONFIDENCE

代表：
- PRE_3K
- 更強量能
- 更大突破幅度
- 更長突破持續

### 🔁 SECOND_BREAKOUT

代表：
- 曾經失效
- 再次有效突破

---

# 20. 通知去重

不能使用單純：

```text
N 分鐘內不通知
```

作為唯一規則。

正式設計：

```text
State Machine
+
Event ID
+
Snapshot Identity
+
Cooldown
+
Oscillation Protection
```

## 20.1 每檔主要通知上限概念

同一檔股票通常：

```text
1. First BREAKOUT
2. PRE_3K
3. HIGH_CONFIDENCE
4. SECOND_BREAKOUT（若有重大重新突破）
```

不得每 20 秒重複通知同一狀態。

---

# 21. Telegram 每日通知上限

V1.0：

```text
Daily hard ceiling = 50 major notifications
```

50 是：

> 硬上限，不是目標數量。

預期正常交易日：

```text
約 10–30 則
```

超過 50 時，依優先級排序：

```text
P1 HIGH_CONFIDENCE
P2 PRE_3K
P3 BREAKOUT
P4 SECOND_BREAKOUT
```

低優先級訊號應被抑制，而不是突破上限。

---

# 22. Market Regime

## 22.1 定位

Market Regime 是：

`Context`

不是：

`Hard Filter`

不能因為大盤不好，就阻擋一檔符合個股條件的強勢突破。

## 22.2 市場廣度

使用 MIS 全市場資料計算：

```text
advance_count
decline_count
flat_count
valid_stock_count
```

### ADR

```text
ADR =
advance_count / max(decline_count, 1)
```

### Breadth

```text
breadth =
(advance_count - decline_count)
/
valid_stock_count
```

## 22.3 Regime

概念上：

```text
RISK_ON
NEUTRAL
RISK_OFF
```

判斷參考：

```text
指數方向
+
市場廣度
```

## 22.4 使用原則

例如：

```text
市場環境：RISK_OFF
個股狀態：逆勢突破
```

這不是拒絕訊號，而是提高資訊價值。

所有 threshold 必須透過後續 log 實證調整。

---

# 23. Ground Truth

## 23.1 時間

收盤後：

```text
13:30+
```

使用完成日 K 線。

## 23.2 判定

重新以正式 Stage 0–3 規則判斷：

```text
Stage 0
Stage 1
Stage 2
Stage 3
```

全部 PASS：

```text
3K PASS
```

否則：

```text
3K FAIL
```

## 23.3 禁止污染

盤中事件發生後：

> 不得使用收盤結果修改當時的預測資料。

例如：

盤中 10:15：

```text
PRE_3K
```

收盤後：

```text
3K FAIL
```

正確做法是：

```text
10:15 event = PRE_3K
13:30+ ground_truth = FAIL
```

而不是把 10:15 event 改成 FAIL。

---

# 24. Signal Evaluation

每個事件都應可被後續統計。

至少評估：

```text
BREAKOUT → 3K success
PRE_3K → 3K success
HIGH_CONFIDENCE → 3K success
```

並切分：

```text
時間
市場環境
突破幅度
量能倍率
產業
PRESELECTED / DISCOVERY
FIRST / SECOND BREAKOUT
```

---

# 25. Event Log

建議：

```text
logs/YYYY-MM-DD_events.jsonl
```

每行一個 JSON event。

## 25.1 必備欄位

```text
date
time
symbol
name

source
state
previous_state

price
today_open
prev_close
up_pct

k1_high
k2_high
breakout_level
breakout_pct

current_volume_lots
yesterday_volume_lots
vma5_lots

estimated_eod_volume_lots
estimated_vs_yesterday
estimated_vs_vma5

stage1_pass
stage2_pass
stage3_projected_pass

breakout_hold_count

score
market_regime

event_id
notification_sent
```

---

# 26. Post-Signal Tracking

每次重大訊號可追蹤：

```text
+5m
+15m
+30m
+60m
Close
```

記錄：

```text
max_price_after_signal
max_gain_pct
close_price
close_gain_pct
final_3k_pass
```

目的：

> 找出哪一種盤中訊號最有預測價值。

---

# 27. 不得預先假設成功率

本策略目前沒有宣稱：

```text
BREAKOUT 成功率 = X%
PRE_3K 成功率 = Y%
HIGH_CONFIDENCE 成功率 = Z%
```

原因：

真正可信的成功率必須由：

```text
實際事件 Log
+
收盤 Ground Truth
```

統計得到。

---

# 28. 未來量化校準

累積足夠資料後，可以建立：

```text
P(3K PASS | state, time, score, volume_ratio, breakout_pct, regime, source)
```

例如：

```text
P(3K PASS | HIGH_CONFIDENCE, 10:30, score=94)
```

再進一步建立：

```text
Calibration Curve
Precision
Recall
F1
Brier Score
ROC-AUC
PR-AUC
```

但這些屬於 V1.1+ 的統計校準工作。

---

# 29. Look-ahead Bias 防護

任何時間點 T 的判斷：

> 只能使用 T 當下或 T 之前已知的資料。

禁止：

```text
用收盤價預測 10:15
用 13:30 成交量修改 10:15 分數
用事後最高價判定盤中是否應該發訊號
```

正確：

```text
T 時刻 snapshot
→
T 時刻可知資料
→
T 時刻策略判斷
→
事件 Log
→
未來 Ground Truth
```

---

# 30. 邊界條件

所有正式 threshold 都必須測試：

```text
threshold - epsilon
threshold
threshold + epsilon
```

至少包含：

### Stage 2

```text
gain = 3.99%
gain = 4.00%
gain = 4.01%
```

### Effective breakout

```text
0.299%
0.300%
0.301%
```

### Stage 3

```text
VMA5 = 999
VMA5 = 1000
VMA5 = 1001

ratio = 1.499
ratio = 1.500
ratio = 1.501
```

### HIGH_CONFIDENCE

```text
breakout = 0.499%
breakout = 0.500%
breakout = 0.501%
```

---

# 31. 策略錯誤防護

以下情況不得產生正常訊號：

```text
current_price <= 0
prev_close <= 0
breakout_level <= 0
yesterday_volume <= 0
vma5 <= 0
elapsed_minutes <= 0
invalid symbol
missing required field
timestamp invalid
```

資料缺失：

> 應該是 `UNKNOWN / NO SIGNAL`，不是自動 PASS。

---

# 32. 盤中 Discovery

Discovery 的目的：

> 不讓 08:20 沒入選的股票完全失去機會。

但 Discovery 不應降低正式 3K 的標準。

至少需要：

```text
current_price > K1 High
current_price > K2 High
gain >= 4%
effective breakout >= 0.3%
2 consecutive valid snapshots
```

後續再結合：

```text
projected volume
trend context
market regime
```

形成 Intraday Signal。

---

# 33. 兩種訊號來源必須分開

Event：

```text
source = PRESELECTED
```

或：

```text
source = INTRADAY_DISCOVERY
```

不可混淆。

原因：

後續統計必須回答：

> 盤前篩選本身有多大價值？

以及：

> 純盤中發現的股票有多大價值？

---

# 34. V1.0 核心流程

```text
                08:20
                  │
                  ▼
             FULL_SCAN
                  │
                  ▼
               Stage 0
                  │
                  ▼
               Stage 1
                  │
                  ▼
               Stage 2
                  │
                  ▼
               Stage 3
                  │
                  ▼
        Preselected Pool
          + Daily Context
                  │
                  ▼
                09:00
                  │
          MIS every 20 sec
                  │
          ┌───────┴────────┐
          ▼                ▼
    Preselected       Intraday Discovery
          │                │
          └───────┬────────┘
                  ▼
          Intraday 3K Engine
                  │
                  ▼
 WATCH → APPROACHING → BREAKOUT
                         │
                         ▼
                      PRE_3K
                         │
                         ▼
                 HIGH_CONFIDENCE
                         │
              ┌──────────┴──────────┐
              ▼                     ▼
       BREAKOUT_LOST         Telegram Event
              │
              ▼
       SECOND_BREAKOUT
              │
              ▼
           13:30+
              │
              ▼
        Ground Truth
              │
        ┌─────┴─────┐
        ▼           ▼
     3K PASS     3K FAIL
```

---

# 35. V1.0 不做的事情

為避免第一版過度複雜，以下暫不作為硬條件：

- 籌碼面硬篩
- 法人買超硬篩
- 融資融券硬篩
- 權證主力硬篩
- SMC 金蛋蛋硬篩
- TIDE 硬篩
- 新聞情緒硬篩
- AI 情緒分數硬篩
- 盤中複雜機器學習模型
- 自動調參
- 未經驗證的機率模型

這些可以作為：

`V1.1+ Feature Candidates`

---

# 36. 與 V2.4 的關係

V2.4：

```text
Production / Immutable
```

V1.0：

```text
Independent Research / New Engine
```

V2.4 可以提供：

- MIS 批次抓取經驗
- API 使用經驗
- 交易時間控制
- 已驗證的市場資料來源
- SMC / TIDE 等未來擴充概念

但：

> V1.0 不得為了方便而直接修改 V2.4。

---

# 37. 策略優先順序

當規則互相衝突：

```text
Canonical 3K Definition
>
Ground Truth Definition
>
Intraday Prediction Definition
>
Score
>
Market Regime
>
Future Features
```

Score 不能推翻硬條件。

Market Regime 不能推翻硬條件。

未來 Feature 不能偷偷改寫 V1.0。

---

# 38. 版本控制

策略修改必須：

```text
V1.0
V1.1
V1.2
...
```

不得直接修改歷史版本的意義。

每次策略變更必須說明：

```text
Changed Rule
Reason
Expected Effect
Backtest Result
Live/Paper Result
```

---

# 39. V1.0 最終定義

### Daily 3K

```text
Stage 0 PASS
AND
Stage 1 PASS
AND
Stage 2 PASS
AND
Stage 3 PASS
```

### Intraday Effective Breakout

```text
current_price >= breakout_level × 1.003
AND
2 consecutive valid snapshots
```

### PRE_3K

```text
Effective Breakout
AND
Gain >= 4%
AND
Projected EOD Volume >= Yesterday Volume
AND
Projected EOD Volume >= 1.5 × VMA5
AND
Breakout holds
```

### HIGH_CONFIDENCE

```text
PRE_3K
AND
Projected EOD Volume >= 1.8 × VMA5
AND
Breakout >= 0.5%
AND
3+ valid snapshots holding
```

### Ground Truth

```text
Post-close Stage 0–3
```

才是：

`3K PASS`

---

# 40. 最重要的策略哲學

天機 3K V1.0 不追求：

> 每天抓最多股票。

而是追求：

> 在正式 3K 尚未完成以前，盡可能早、盡可能穩定地找到正在完成 3K 結構的股票。

核心邏輯：

```text
趨勢
+
突破
+
量能
+
時間
+
持續性
+
市場環境
=
盤中 3K 預測
```

最終用：

```text
盤中 Event
+
收盤 Ground Truth
+
長期統計
```

讓策略從：

`Rule-based`

逐步進化成：

`Empirically Calibrated Quantitative Signal Engine`

---

# Appendix A：Canonical Threshold Table

| Parameter | V1.0 |
|---|---:|
| FULL_SCAN | 08:20 |
| Market Open | 09:00 |
| Market Close | 13:30 |
| MIS Poll | 20 sec |
| Stage 0 Yesterday Volume | >= 500 lots |
| Stage 1 MA | 20 / 60 |
| Stage 2 Gain | >= 4.0% |
| Stage 2 High Break | K1 / K2 |
| Effective Breakout | >= 0.3% |
| Effective Breakout Confirm | 2 snapshots |
| Stage 3 VMA5 | >= 1,000 lots |
| Stage 3 vs Yesterday | > 1.0x |
| Stage 3 vs VMA5 | >= 1.5x |
| HIGH_CONF vs VMA5 | >= 1.8x |
| HIGH_CONF Breakout | >= 0.5% |
| Breakout Lost Buffer | -0.3% |
| Daily Telegram Hard Cap | 50 |

---

# Appendix B：術語

### 3K
天機正式三階段日 K 結構：

```text
Trend + Breakout + Volume
```

### Daily Context
盤前已知且鎖定的歷史市場結構。

### Effective Breakout
突破前兩日高點後，再至少超出 0.3%。

### PRE_3K
盤中高度接近正式 3K 條件，但尚未取得收盤 Ground Truth。

### HIGH_CONFIDENCE
盤中條件完成度更高的訊號狀態。

### Ground Truth
收盤後使用完整已完成日 K 所判定的真實結果。

### Look-ahead Bias
使用判斷時間點之後才知道的資料。

---

文件結束。
