# Tianji 3K v1.2.10 — Second Batch: Per-Prediction Validation Loop

## Scope

This patch completes the second batch on top of the v1.2.10 Telegram-reliability candidate. It does not change Stage 0–3 filters, signal thresholds, MIS polling cadence, worker count, Telegram message formatting, `.env`, or market-data API frequency.

## Changes

- Added `validation/post_signal_tracker.py`, a durable per-`prediction_id` price tracker.
- Tracks +5m, +15m, +30m price samples from existing MIS Radar snapshots only; no additional market-data requests are made.
- Records return %, observed MFE/MAE, source snapshot identity, and sample timestamp. A milestone missed by more than the 120-second grace window is explicitly marked `MISSED_WINDOW`, never misrepresented as an on-time sample.
- Atomically persists tracker state at `predictions/<trade_date>/post_signal_tracking.json`; a restarted process restores extrema, milestone states, and last snapshot identity.
- Finalizes one `POST_SIGNAL_TRACKING_FINAL` event per prediction ID with close price/return, MFE/MAE, Ground Truth availability, and missing milestones. Finalization is idempotent.
- Writes `validation/post_signal_tracking_<trade_date>.csv` and `.json`, one row per prediction ID.
- Hooks tracker into the existing Radar loop and existing Ground Truth completion / 13:35 cutoff flow. Tracking failures are isolated and logged so they do not stop Radar.
- Recovery logs now include the number of durable predictions to make restart recovery auditable.

## Validation

- `python -m compileall -q tianji_3k`: passed.
- `pytest -q`: **158 passed**.
- Tests cover milestone sampling, missed-window classification, MFE/MAE, restart restoration, snapshot de-duplication, per-prediction close finalization, idempotency, unavailable Ground Truth, and report export.

## Known limits

- MFE/MAE is based on valid MIS snapshots observed after the signal plus the official close. It is not tick-level truth and can miss intracycle extremes.
- This increment does not add next-session tracking. Next-session continuation should be added as a separate, tested extension if required.
- The patch is a local candidate until applied to the user's repository and CI passes there.
