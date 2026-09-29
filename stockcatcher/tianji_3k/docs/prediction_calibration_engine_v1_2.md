# Prediction Calibration Engine — V1.2

## 目的
將不可變的 `INTRADAY_3K_PREDICTION` 與收盤 `Ground Truth` 做歷史校準，產生可審計的經驗統計。

## 輸入
- `validation/master_prediction_log.jsonl`
- `validation/master_ground_truth_log.jsonl`
- Join key：`trade_date + symbol`

## 輸出
- `validation/score_calibration.json`：累積歷史報告
- `validation/score_calibration_YYYY-MM-DD.json`：當日報告

## 指標
1. Score 0–100 分箱：0–59、60–69、70–79、80–89、90–100
2. Trigger hour：09、10、11、12、13
3. sample / hit / miss
4. empirical hit rate
5. 95% Wilson interval
6. sample stability：預設至少 30 個事件才標記 stable

## 重要限制
- Score **不是機率**。
- Wilson interval 只是歷史樣本不確定性的描述。
- 未取得 Ground Truth 的事件不進入命中率分母。
- 無效 Score 不進入校準，另計 `invalid_score`。
- 同一交易日同一股票若因 re-arm 產生多個 prediction event，事件層級統計會重複使用同一日 Ground Truth；報告會明確標示此限制。
- V1.2 不根據校準結果自動修改 Stage 0–3 或 Prediction Score 權重。
