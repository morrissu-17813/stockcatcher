# 天機 3K 盤中預判引擎 V1.0 Production

這個版本把已完成模組整合成單一交易日 Production Pipeline：

`Stage 0 → Stage 1 → Stage 2 → Stage 3 → Final 3K Pool → PREMARKET_WATCHLIST → MIS 20s Radar → State Machine → Volume Projection → INTRADAY_3K_PREDICTION → Telegram Gate → Prediction Ledger → Ground Truth → PREDICTION_VALIDATION → Daily Report → Safe Shutdown`

## 執行

在既有 `stockcatcher` 專案根目錄執行，使用既有根目錄 `.env`，不要建立新的 `.env`：

```powershell
python -m tianji_3k --preflight
python -m tianji_3k --run

# 人工持續監控／測試（不受盤中時間限制）
python -m tianji_3k --manual-monitor --no-telegram
```

測試模式：

```powershell
python -m tianji_3k --once --no-telegram
python -m tianji_3k --intraday-once --no-telegram
python -m tianji_3k --ground-truth-once --no-telegram
python -m tianji_3k.tools.failure_injection
```

## Production 保證

- 同一交易日只允許一個 Production Runner。
- Runtime checkpoint 與每日 state atomic write。
- Prediction 先持久化，再送 Telegram；重啟後可安全重試未確認通知。
- 相同 `data_identity` 不可重複構成兩次有效確認。
- 觸發後必須失效並重新形成有效突破，才可 re-arm。
- `up_pct >= 9.50%` 不送 Telegram，但保留 SUPPRESSED 歷史事件。
- Ground Truth 13:30 後持續重試至 13:35 cutoff。
- Prediction 永不被 Ground Truth 覆蓋；兩者透過 `prediction_id` + `chain_hash` 串接。
- 每日報告分母只包含已完成 Ground Truth 的 `INTRADAY_3K_PREDICTION`。
- 不包含下單功能；本系統為盤中監控、預判、通知與驗證。


## Production Data Integrity V1.0.1

資料層現在採用 Trading Calendar 驅動的增量更新與缺日自動補抓。正式上線前建議先清除開發期 `cache/daily`，重新建立乾淨歷史基線；正式營運後只做增量更新與必要補抓。

詳細規格：`docs/production_data_integrity_v1.md`。
