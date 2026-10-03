# Dynamic Discovery v1.0.4

## 本版目的

將盤中動態選股正式獨立為 Dynamic Discovery Spec，讓 Production 可以在盤中持續從全市場發現新的 3K 潛力股，而不改動既有盤前 Stage 0~3 3K Core。

## 變更

1. 新增 `core/dynamic_discovery.py`
   - 全市場 MIS-only candidate gate。
   - 只對少量候選進行歷史 enrichment。
   - 昨量 >= 1000 張。
   - 今日漲幅 >= 3%。
   - 現價 > 今日開盤。
   - 今日累積量 >= 300 張。
   - 成交量 pace >= 0.8（依 09:00~13:30 session elapsed normalization）。
   - 每輪最多 3 檔新的歷史 enrichment。
   - 單檔最多 3 次歷史取得嘗試。

2. `core/dynamic_candidate.py`
   - 移除 KD 計算與 KD audit 欄位。
   - 明確標記 Dynamic Candidate 不等於 Stage 0~3 PASS。
   - `stage0_pass=False`、`dynamic_discovery_pass=True`。

3. `runner.py`
   - 使用獨立 Dynamic Discovery engine。
   - 維持 MIS 為全市場盤中 discovery source。
   - FinMind 僅 selective enrichment，不做全市場逐檔查詢。
   - Fugle 5m 仍只在 State Machine 真正突破觸發後呼叫。
   - Radar 改為固定 20 秒 cadence，將本輪處理時間包含在 interval 內，降低 30~40 秒漂移。

4. 新增 `docs/DYNAMIC_DISCOVERY_SPEC.md`
   - 正式記錄資料來源、Gate、API load policy 與邏輯邊界。

## 未變更

- 盤前 Stage 0~3。
- Stage 1 四條件。
- Stage 2 紅K/4%/前兩日高點突破。
- Stage 3 5日均量/今日量/1.5x。
- Intraday State Machine 兩次 distinct MIS confirmation。
- Breakout buffer 0.3%。
- Fugle 5m micro confirmation 1.2x。
- Projected Volume 1.5x hard gate。
- Telegram notification flow。
- Ground Truth / 13:30 validation / 13:35 STOP。
- 2TON、SMC 金蛋蛋、KD 等未確認條件。
