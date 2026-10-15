# Tianji 3K Production v1.2.9 — P0 Reliability Fixes

## Scope

This release is a minimal reliability patch based on the 2026-10-15 production log. It does not add the planned signal-quality scoring layer.

- MIS quote coverage now distinguishes a symbol present in the raw MIS `msgArray` but missing a usable `z` last price from a symbol absent from the raw response. This improves diagnosis without substituting previous close or loosening quote freshness rules.
- EARLY live-volume wait logs now include estimator sample count and the reason its observation history was reset (clock reversal, same-time conflicting volume, excessive gap, or cumulative-volume rollback). The estimator thresholds and reset behavior are unchanged.
- Ground Truth now logs start/result counts and duration, reuses durable same-day Ground Truth rows instead of repeatedly fetching completed symbols, and retries only unresolved prediction symbols after the first full pass.
- Ground Truth completion is based on all prediction symbols having a durable result, rather than any non-empty partial result. Missing validation is not permanently frozen during the retry window; unresolved predictions are marked unavailable only at the 13:35 cutoff.
- Stage 0-3 conditions, EARLY/STRONG/MOMENTUM decision thresholds, Telegram behavior, MIS radar target interval, API worker count, and `.env` values are unchanged.

## Validation

- Full test suite: **144 passed**.
- `compileall`: passed.
- Added assertions for MIS raw-symbol versus missing-price diagnostics.
- Added assertions for EARLY volume estimator reset diagnostics.
- Full test suite result is recorded with the release package after execution.
