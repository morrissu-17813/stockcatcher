# 天機 3K Production v1.0.7

## 目的

修正本地人工測試時，直接執行 `python -m tianji_3k --run` 在非盤中時間立即結束的問題。

## 行為

### 本機互動環境

當使用：

```powershell
python -m tianji_3k --run
```

且目前不是 `RADAR` 盤中階段時，Runner 自動切換至：

```text
MANUAL MONITOR
```

持續執行完整既有 MIS Radar / Dynamic Discovery / State Machine / Fugle 5m / Projected Volume 預判鏈。

### 明確手動模式

仍可直接使用：

```powershell
python -m tianji_3k --manual-monitor
```

或：

```powershell
python -m tianji_3k --manual-monitor --no-telegram
```

### 線上 / CI / GitHub Actions

非互動環境執行 `--run` 不會自動切換 Manual Monitor，仍維持正式交易日 lifecycle：

```text
08:20 PREMARKET
09:00 RADAR
13:30 GROUND_TRUTH
13:35 STOP
```

## 安全邊界

本版本沒有修改：

- Stage 0~3 3K 規則
- Dynamic Discovery gate
- State Machine gate
- Fugle 5m confirmation
- Projected Volume >= 1.5x
- Telegram notification logic
- KD / 2TON / SMC

Manual Monitor 仍使用真實可取得的 MIS snapshot；非交易時段不會偽造市場價格或虛構盤中成交資料。

## 測試

```text
104 passed / 0 failed
```
