# V24 Paper Exit Lifecycle

## Goal
Extend the isolated AI Quant Lab paper account with an explicit, auditable stop-loss/take-profit exit evaluation event. Ground Truth remains deferred.

## New event
`paper.exit_check`

Example payload:
```json
{
  "mode": "paper",
  "symbol": "2330",
  "mark_price": "97.00",
  "stop_loss_pct": "0.02",
  "take_profit_pct": "0.04",
  "market_snapshot": {"data_age_seconds": 1}
}
```

- `mode` must explicitly be `paper`.
- `market_snapshot` is required and must pass the existing freshness validator; exits fail closed when data is absent/stale/invalid.
- Default thresholds are 2% stop loss and 4% take profit, calculated against the position average cost (which includes buy-side commission).
- When triggered, the entire open long position is closed in the paper ledger and the event result records `exit_reason` (`STOP_LOSS` or `TAKE_PROFIT`) and the simulated fill.
- When no position exists or no threshold is triggered, no fill is created.
- The event uses the existing persistence path; when the store supports `commit_event`, the paper fill and event are committed through the existing atomic path.

## Safety and scope
- No broker APIs, live order endpoints, production Tianji 3K/TIDE imports, `.env` changes, schema changes, or new tables.
- This is an event-driven paper exit evaluator, not a background market watcher. A caller must supply a fresh market mark and explicitly submit the event.
- `max_order_notional` is enforced for exits as well as entries.
- Ground Truth and real-market profitability claims are not included.

## Validation
- `python -m pytest -q`: 107 passed.
- `python -m compileall -q .`: passed.
- Supabase live commit/restart recovery is not claimed as tested by this local run.
