# Tianji 3K Production v1.2.10 — Telegram Delivery Reliability Fix

## Incident addressed

Based on the 2026-10-20 production log, an EARLY prediction for 5340 建榮 was persisted, then a Telegram `ReadTimeout` escaped from `sendMessage` through `reconcile_pending_notifications()` and terminated the runner with exit code 1. Because the first send attempt did not persist a final notification status, reconciliation could immediately resend the same prediction, creating duplicate-message risk.

## Changes

- Telegram transport failures are converted into durable results rather than escaping into the Radar loop. `ReadTimeout`, ambiguous connection failures, malformed responses, and HTTP 5xx responses are marked `UNKNOWN`; connection-establishment timeouts and explicit HTTP 4xx failures are marked `FAILED`.
- Prediction notification sending writes `SENDING` before the network request, then persists the final status, error type, and error text.
- `UNKNOWN` and `SENDING` notifications are never blindly resent. Stale `SENDING` attempts are converted to `UNKNOWN` for audit.
- `FAILED` notifications are retried only after a 60-second cooldown; this prevents an immediate second send in the same Radar cycle.
- Reconciliation exceptions are isolated and logged so the notification side path cannot terminate the main Radar loop.
- The same helper is used by MIS-LIVE EARLY and Fugle 5M prediction notifications to keep behavior consistent.
- Existing Stage 0–3 selection conditions, prediction thresholds, Telegram message format, MIS radar cadence, worker count, and `.env` settings are unchanged.
- Existing v1.2.9 P0 diagnostics for MIS quote coverage, EARLY volume observation, and Ground Truth close validation are retained.

## Delivery semantics

Telegram `sendMessage` has no client-provided idempotency key. A read timeout may mean the message was accepted but the response was lost. To avoid duplicate alerts, such cases are recorded as `UNKNOWN` and are not automatically resent; the operator should check Telegram delivery before manually retrying. This favors duplicate prevention over guaranteed delivery in ambiguous cases.

## Validation

- Python `compileall`: passed.
- Full test suite: **151 passed**.
- Added tests for ReadTimeout, ConnectTimeout, HTTP 5xx, UNKNOWN no-resend behavior, FAILED cooldown, stale SENDING state, and runner exception containment.
- This validates the local package; GitHub Actions deployment still needs to run on the new commit.
