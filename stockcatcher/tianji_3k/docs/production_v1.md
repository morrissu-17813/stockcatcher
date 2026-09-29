# 天機 3K 盤中預判引擎 V1.0 Production

## Lifecycle
08:20 premarket scan -> PREMARKET_WATCHLIST -> 09:00-13:30 MIS Radar -> INTRADAY_3K_PREDICTION -> 13:30-13:35 Ground Truth -> 13:35 safe shutdown.

## Source of truth
Prediction Ledger is the durable source of truth. Runtime checkpoint and runtime_state are recovery aids only.

## Recovery
- Atomic JSON checkpoint writes.
- Per-day runtime state persists state machines.
- Prediction is persisted before Telegram.
- Restart reconciles unsent notifications idempotently.
- Ground Truth is retried until the 13:35 cutoff.
- A single process lock prevents two production runners from polling the same day simultaneously; stale locks from crashed processes are recoverable.

## Notification semantics
- PREMARKET_WATCHLIST: observation pool, not a signal.
- INTRADAY_3K_PREDICTION: confirmed price + projected volume trigger.
- UP_PCT >= 9.50%: Telegram suppressed but ledger event retained.
- GROUND_TRUTH: post-close validation for symbols that produced predictions.

## Commands
```powershell
python -m tianji_3k --preflight
python -m tianji_3k --once --no-telegram
python -m tianji_3k --intraday-once --no-telegram
python -m tianji_3k --ground-truth-once --no-telegram
python -m tianji_3k --run
```

## Safety
No order execution is implemented. The Production runner is a monitoring/prediction/validation system only.
