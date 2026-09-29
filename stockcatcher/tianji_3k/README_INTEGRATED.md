# 天機 3K V1.0 — Integrated Drop-in

這一版是直接依既有 `stockcatcher/tianji_3k/` 結構整合，不建立第二個專案，也不使用 `tianji_3k/.env`。

## 主要資料鏈

`Stage 0 → Stage 1 → Stage 2 → Stage 3 → Final 3K Pool → MIS Radar → State Machine → Prediction Ledger → Ground Truth → Daily Validation`

## 共用設定

使用既有專案根目錄 `.env`。程式會由 `data/config.py` 自動尋找，不會建立新的 `.env`。

## 執行

盤前／單次建立觀察池：

```powershell
python -m tianji_3k --once --no-telegram
```

盤中單次 Radar：

```powershell
python -m tianji_3k --intraday-once --no-telegram
```

正式盤中循環（20 秒）：

```powershell
python -m tianji_3k --run
```

13:35 自動結束；13:30~13:35 執行 Ground Truth。

## 重要輸出

- `tianji_3k/cache/stage0_production.json`
- `tianji_3k/cache/stage1_trend.json`
- `tianji_3k/cache/stage2_breakout.json`
- `tianji_3k/cache/stage3_volume.json`
- `tianji_3k/cache/final_3k_pool.json`
- `tianji_3k/predictions/YYYY-MM-DD/<symbol>/context.json`
- `tianji_3k/predictions/YYYY-MM-DD/<symbol>/events.jsonl`
- `tianji_3k/predictions/YYYY-MM-DD/<symbol>/ground_truth.json`
- `tianji_3k/validation/daily/YYYY-MM-DD.json`

## 測試

```powershell
pytest -q tianji_3k/tests
```

## V2.1 穩定化重點

- 每個交易日使用 `cache/pools/YYYY-MM-DD.json` 固化當日盤前觀察池，避免隔日誤用前一日 Final Pool。
- `predictions/YYYY-MM-DD/runtime_state.json` 持久化 Radar state，程式重啟後可恢復 WATCHING / BREAKOUT_PENDING / TRIGGERED 等狀態。
- 同一 data identity 不得重複計入兩次有效確認。
- `TRIGGERED` 後必須先失效，再重新形成兩筆有效 snapshot，才允許再次觸發。
- Prediction 以 `prediction_id` 永久保存，Ground Truth 與 Notification 均為獨立 append-only 事件。
- Ground Truth 與 Telegram Ground Truth 具冪等保護，重跑不重複寫入驗證事件或重複通知。
- 新增 `tools/preflight.py` 與 `tools/replay_intraday.py`，在實盤前可做結構檢查與 deterministic replay。
