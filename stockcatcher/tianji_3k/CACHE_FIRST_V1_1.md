# Tianji 3K Cache First V1.1

## Data flow

`cache\\daily` → valid local OHLCV → Stage 0~3

If a symbol has no valid local cache for the requested range:

`FinMindDailyProvider` → fallback

FinMind failure does not invalidate successful cache hits.

## Logging

- `CACHE_HIT`
- `CACHE_MISS`
- `CACHE_INVALID`
- `FINMIND_FAILED`

The runner prints provider statistics at FULL_SCAN completion.

## Important

This patch does not change the Stage 0~3 rules. It changes only the daily-data acquisition path.
