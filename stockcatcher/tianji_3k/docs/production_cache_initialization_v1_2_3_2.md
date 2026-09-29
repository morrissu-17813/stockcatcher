# 天機 3K — Production Cache 全量初始化 / 580/hr Pause-Checkpoint-Resume

## 目的

在 V1.2.3.2 穩定基線上，提供一次性的 Production daily-cache 建置流程：

1. 使用台股 TWSE / TPEx 現行普通股 Universe。
2. 先取得 Trading Calendar。
3. 每支股票確保至少 61 個有效交易日的 daily K。
4. Cache-first：完整 Cache 不消耗 FinMind request。
5. 缺資料時每支股票最多以一次 FinMind history request 補齊整段需求區間。
6. FinMind 採共享 rolling 60-minute / 580-request safety gate。
7. 到達 580 時寫入 checkpoint，不把剩餘股票誤判成資料失敗。
8. 可重新啟動並從 pending symbol 繼續；已完成股票不重抓。
9. `--initialize-cache` 預設會等待 rolling window 釋放後自動繼續。
10. `--init-no-wait` 則在觸頂後立即保存 checkpoint 並退出，下一次啟動即可 Resume。

## 執行

```powershell
python -m tianji_3k --initialize-cache
```

不等待：

```powershell
python -m tianji_3k --initialize-cache --init-no-wait
```

預設需求為 61 個有效交易日，可用 `--init-bars` 調整。

## Checkpoint

位置：

```text
tianji_3k/cache/production_cache_initialization.json
```

重要欄位：

- `status`: `RUNNING` / `PAUSED_BUDGET` / `PAUSED_ERROR` / `COMPLETE`
- `all_symbols`
- `completed_symbols`
- `pending_symbols`
- `current_symbol`
- `latest_completed_date`
- `start_date`
- `bars_required`
- `budget`

Checkpoint 是恢復控制資料，不取代 daily cache 本身。

## 安全規則

- 580 本身就是阻擋點：`used >= 580` 不再送下一個 FinMind request。
- rolling window，不是每個整點歸零。
- 舊 request 滾出 60 分鐘後恢復。
- 不刪除既有 Production cache；完整 Cache 命中時不會重新抓。
- Universe discovery 若只有異常少量資料會 fail-closed，不會產生假的 `COMPLETE`。
