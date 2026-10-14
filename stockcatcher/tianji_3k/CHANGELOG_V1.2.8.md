# Tianji 3K Production v1.2.8

## Minimal production fixes based on 2026-10-14 intraday logs

- Fix EARLY-MIS estimator duplicate observation handling: an identical timestamp + cumulative volume observation is idempotent and no longer clears warmed volume history. Counter rollback, same-time conflicting counters, backwards timestamps, and gaps above 240s still reset the window.
- Keep Stage 0-3 selection rules, breakout thresholds, quote freshness limits, 300s trigger TTL, notification levels, deduplication, 20s Radar target, and 4-worker MIS/Fugle pools unchanged.
- MIS batch workers now report raw `msgArray` item counts and parse rejection reasons (missing symbol, invalid previous close, missing last price, unknown exchange quote time), plus per-batch requested/raw/parsed/failed summaries. This diagnoses low parsed coverage without loosening quote validity.
- Add per-Radar active-context quote coverage summary (`raw_present`, `accepted`, stale/unknown, invalid, missing raw).
- Add persisted bounded backoff for dynamic history API exceptions: exponential 60s/120s backoff before the next allowed attempts (the existing three-attempt cap remains unchanged). Successful/ineligible history evaluation retains the existing attempt cap and candidate eligibility logic. No Stage 0-3 condition changed.
- Add Telegram send timing and signal trigger-age/received-snapshot-age logs for EARLY-MIS and Fugle paths.
- No extra history API is called for EARLY-MIS volume estimation.

## Validation

Regression and new targeted tests are run against the complete package. Live-market behavior still requires a trading-session replay/deployment test.
