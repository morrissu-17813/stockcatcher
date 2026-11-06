# 天機 3K Production v1.3.0 — Strategy Intelligence

## 版本定位

本版把 v1.2.10 的盤中追蹤、v1.2.11 的唯讀影子驗證與 v1.2.12 的 Prediction Ledger 完整化整合為可離線產生的策略研究報告。新增分析僅讀取既有標準化資料，不參與正式交易決策。

## 新增功能

- 新增 `validation/strategy_intelligence.py`：讀取 `shadow_validation_dataset.json`，輸出策略研究 JSON、CSV 分組表、Markdown 報告與獨立 HTML 儀表板。
- 提供正式 Ledger 收盤報酬、觀察 MFE/MAE、分數區間、預估量比區間、訊號時間與訊號級別的描述性統計。
- 顯示樣本數、正／負／平、平均／中位報酬與 Wilson 95% 區間。
- 將 Excel 歷史代理報酬與 Ledger 正式收盤結果分開計算，禁止混為同一績效樣本。
- 缺少收盤結果標記為 UNKNOWN，不納入勝負分母。
- 報告輸出目錄非空時拒絕覆寫，保留每次研究快照。

## 執行方式

先產生標準化影子資料集：

```powershell
python -m tianji_3k.validation.shadow_validation --prediction-root predictions --validation-root validation --output-dir validation\research\shadow_20261106
```

再產生策略研究報告：

```powershell
python -m tianji_3k.validation.strategy_intelligence --dataset validation\research\shadow_20261106\shadow_validation_dataset.json --output-dir validation\research\intelligence_20261106
```

如需匯入歷史 Excel，第一個指令加上 `--signal-xlsx <檔案路徑>`。

## 不變項目

- Stage 0–3 選股條件與門檻不變。
- MIS Radar 輪詢頻率、資料來源與呼叫頻率不變。
- Telegram 通知格式、時機、去重與失敗處理流程不變。
- 不修改 `runner.py`，不新增即時行情 API 呼叫。
- 不新增正式交易訊號、不自動調整策略參數。
- 不把 2TON／SMC 納入正式選股流程。

## 驗證

- 以使用者 2026-11-06 上傳版本作為基準。
- 基準回歸：165 passed。
- v1.3.0 新增測試涵蓋 UNKNOWN 排除、代理報酬分離、分組統計與輸出防覆寫。
- 交付前執行完整套件測試與 compileall。

## 限制

- 目前標準 Master Ledger 只有 1 筆正式預測事件；目前缺少 `master_ground_truth_log.jsonl`。因此本次研究結果的樣本量不足以評估策略優劣。
- Excel proxy return 不等同可成交報酬或扣除成本後的交易損益。
- MFE／MAE 僅反映既有 MIS 快照可觀察到的極值，非逐筆 tick 真值。
- 本版分組結果只供研究，不會自動生成 A/B/C/D 交易評級，也不會變更 Stage 0–3。
