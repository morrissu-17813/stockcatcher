# V1.2.3.2-P1.1

- 修正 `FinMindRequestBudget.seconds_until_available()`
- 支援 rolling 60-minute window 的自動等待
- `ProductionCacheInitializer(wait_for_budget=True)` 可在最早 reservation 過期後繼續
- 完整測試：88 passed
- compileall：PASS
