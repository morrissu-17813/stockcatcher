# Prediction Ledger v2.2 — 資料契約

## Canonical record

正式預測的唯一來源是：

`predictions/<trade_date>/<symbol>/events.jsonl`

`validation/master_prediction_log.jsonl` 是供查詢及彙總使用的可重建索引，不是唯一真實來源。若 master 與 per-symbol 檔案不一致，先稽核，再從 canonical events 重建。

## Prediction event 必備識別欄位

- `prediction_id`：每筆預測唯一識別碼；同一股票不同訊號不得合併。
- `event_id`：該筆事件識別碼。
- `trade_date`、`symbol`、`event_type`。
- `created_at`：訊號觀測時間；`recorded_at`：寫入 Ledger 的 UTC 時間。
- `schema_version=prediction-v2.2`。
- `record_hash`：對事件內容計算 SHA-256，排除 `record_hash` 欄位本身。

## 標準化 signal projection

`signal` 是從既有原始欄位投影而來，缺少欄位保留 null，不推估、不補造：

- signal_level / signal_time / signal_price / breakout_base / extension_pct / up_pct
- projected_volume_ratio / live_volume_ratio / cumulative_volume_lots / vma5_lots
- prediction_score / evidence_source / snapshot_id
- stage0_pass / stage1_pass / stage2_pass / stage3_pass / final_pool / dynamic_candidate

原始 `context`、`trigger_snapshot`、`volume_snapshot` 必須保留，方便未來 schema 擴充與回溯。

## Idempotency

`create_prediction()` 對相同 `trade_date + symbol + snapshot_id + observed_at` 回傳既有 prediction，不重複追加。相同 snapshot label 但不同 observed_at 視為不同觀測，保留獨立 prediction。正式 Runner 原有 `find_prediction_by_snapshot()` 檢查仍保留。

## Lifecycle events

通知狀態、T+5/T+15/T+30 樣本、Ground Truth 與驗證結果必須以獨立 event 追加，透過 `prediction_id` 關聯；不可回寫或修改原始 prediction event。

## 稽核與修復

```powershell
python -m tianji_3k.validation.ledger_audit --root predictions --date 2026-11-05
python -m tianji_3k.validation.ledger_audit --root predictions --rebuild-master
```

`integrity_ok=false` 時先保存原始目錄備份，再分析 duplicate IDs、malformed JSONL、hash mismatch、master missing/orphan IDs。不要直接刪除歷史事件。
