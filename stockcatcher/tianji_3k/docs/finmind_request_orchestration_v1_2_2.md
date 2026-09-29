# 天機 3K V1.2.2 — FinMind Request Orchestration

## Purpose
Prevent a FULL_SCAN from consuming the 580/hour FinMind safety budget before Stage 1 history repair.

## Rules
1. Trading Calendar is bootstrapped once at FULL_SCAN start and shared by DailyDataRefreshManager and CacheFirstDailyProvider.
2. FULL_SCAN no longer refreshes every symbol in the daily cache before Stage 0.
3. Stage 0 candidates are the only symbols eligible for symbol-level latest-bar refresh.
4. One symbol gets at most one FinMind Daily request per `get_daily()` call, even when its cache has multiple missing date segments.
5. History repair uses one full requested range per symbol and persists the merged result.
6. Budget blocks are recorded separately from genuine history/API failures.
7. Runner reserves enough budget for one history request per Stage 0 candidate before spending remaining budget on candidate volume refresh.

## Worst-case plan for 251 Stage 0 candidates
- Trading Calendar: 1 request
- Candidate latest-volume refresh: up to 251 requests
- 61-day history repair: up to 251 requests
- Worst case: 503 requests

The 580 rolling safety limit remains unchanged.
