# V26 — Autonomous Monitor Health and Fail-Closed Recovery

## Scope
Builds on V25 automatic paper stop/take monitoring. No live broker, no production Tianji 3K/TIDE changes, no `.env` edits, no schema migration, and no Ground Truth work.

## Changes
- Expose background thread liveness, monitor health, start time, cycle start/completion, last successful MIS snapshot time, consecutive exception count, and last error through the existing autonomy status response.
- Log each background cycle exception and publish an Auditor warning when possible.
- Stop the autonomous loop after five consecutive unhandled cycle failures.
- Stop immediately when persistence is degraded or restore status is in error; require the existing startup/recovery path before resuming.
- Reset consecutive-error state only after a complete cycle returns successfully.

## Validation
Run `python -m pytest -q` and `python -m compileall -q .` in this project directory. Tests are local-only; provider/Supabase uptime is not simulated as a live integration.
