# 天機 3K V1.2 Quant Validation

## 目的
V1.2 不改變既有 Stage 0~3 與盤中觸發規則，新增「可量化驗證」層，將盤中 Prediction Score 與收盤 Ground Truth 接起來。

## Score Calibration
- 來源：`validation/master_prediction_log.jsonl` + `validation/master_ground_truth_log.jsonl`
- 依 `trade_date + symbol` 對應 Ground Truth。
- 預設分箱：0–59、60–69、70–79、80–89、90–100。
- 輸出每個區間的樣本數、命中數、未命中數、歷史經驗命中率。
- **Score 不是機率**；V1.2 不把分數直接轉成未校準的機率。
- Ground Truth 不可取得的 prediction 不進入命中率分母。
- Score 無效或超出 0–100 的紀錄會被排除並統計於 `invalid_score`。

## FinMind Budget
V1.2 延續 580/hour rolling safety gate：
- `used < 580`：可 reserve。
- `used >= 580`：阻擋新的 FinMind request。
- 60 分鐘前的 reservation 自動退出 rolling window。
- Cache hit 不消耗 FinMind request budget。

## 驗證輸出
可由 Python API 使用：
`build_from_ledger(<tianji_3k>/predictions)`

輸出：`validation/score_calibration.json`


## V1.2.1 Prediction Calibration Engine
- 累積歷史校準：`validation/score_calibration.json`
- 每日校準：`validation/score_calibration_YYYY-MM-DD.json`
- Score 分箱 + Trigger Hour 分箱
- 95% Wilson interval
- 30 samples stability flag
- 不自動修改策略權重
