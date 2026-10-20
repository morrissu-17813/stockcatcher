# V25 — Automatic Paper Stop-Loss / Take-Profit Monitor

## Changes
- Every successful MIS radar cycle evaluates every open paper position.
- Uses `LabEngine.process(paper.exit_check)` for stop-loss and take-profit so existing freshness/risk and durable ledger logic remain in force.
- Default stop loss -2%, take profit +4% relative to paper ledger average cost.
- Requires configured Supabase persistence and a fresh, traded, positive-price quote; missing/stale quotes never trigger exits.
- Adds monitor logs for watch, skipped quotes, errors, and successful paper exits.
- Adds five regression tests for stop loss, take profit, no trigger, stale quote, and missing persistence.

## Safety / limits
- Paper-only; no broker adapter or live-order path added.
- Relies on the existing radar cadence (default minimum 20 seconds) and MIS quote coverage. It cannot guarantee an exchange-side fill at a threshold; paper fill uses the observed quote.
- Live provider and Supabase integration were not available for verification in this build environment.
