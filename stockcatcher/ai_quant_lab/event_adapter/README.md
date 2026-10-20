# 唯讀事件介面

AI Quant Lab 事件引擎支援 `signal.created`、`prediction.recorded`、`prediction.validated`、`telegram.sent`、`telegram.suppressed` 與 `session.closed`。

正式串接天機 3K 時，adapter 只讀取明確指定的 production JSON／JSONL，正規化後直接交給 Lab 引擎；持久化只使用 Supabase 專用表，不建立本機 inbox、SQLite 或其他資料檔。不可在 adapter 內 import 生產 runner、寫入生產 ledger、改變 production 狀態或讀取秘密憑證。

買賣訊號必須在 payload 中明確標記 `mode: "paper"`。來源不明、缺欄位、重複 event ID、超過單筆風險上限或不符合持倉條件時，不得建立成交。

## 真實天機 3K Ledger 唯讀匯入（第三階段）

`production_reader.py` 不匯入 `tianji_3k` Python 模組，只讀取使用者明確指定的資料根目錄，支援：

- `predictions/YYYY-MM-DD/SYMBOL/events.jsonl` 中的 `INTRADAY_3K_PREDICTION`
- `predictions/YYYY-MM-DD/SYMBOL/ground_truth.json`
- `validation/master_prediction_log.jsonl`
- `validation/master_prediction_validation_log.jsonl`
- `validation/master_ground_truth_log.jsonl`

真實 Prediction 只映射成 `prediction.recorded`，Ground Truth／驗證只映射成 `prediction.validated`。**不會將正式訊號轉成 `signal.created`，也不會因此自動產生模擬成交**。若要測試交易策略，必須由 Lab 內明確的策略/風控規則另行產生 `mode: paper` 的模擬委託事件。

先預覽，不寫入任何檔案：

```powershell
python run_lab.py sync-production "..\\tianji_3k" --since 2026-10-01
```

確認來源路徑與事件預覽正確後，若已在後端環境設定 Supabase 憑證，可直接匯入 Lab 的 Supabase 專用事件表：

```powershell
python run_lab.py sync-production "..\tianji_3k" --since 2026-10-01 --ingest
```

此命令不建立任何本機資料檔；未設定 Supabase 憑證時會以記憶體開發模式執行，重啟後不保留資料。匯入的真實預測／驗證事件不會轉成 `signal.created`，也不會自動產生模擬成交。

注意：來源目錄需指向包含 `predictions/` 與 `validation/` 的天機 3K 資料根目錄，不能指向 `ai_quant_lab/`。若部署位置不同，請傳入實際路徑。建議先執行預覽模式。
