# AI Quant Lab V20 — Intraday Execution Safety & Acceptance Foundation

## Scope
V20 is an additive, broker-free safety layer based on V19. It does not enable live orders and does not modify production Tianji 3K/TIDE modules or `.env`.

## Changes
- Added `execution_safety.py` with deterministic market-data freshness checks, a paper order lifecycle (`NEW`, `ACCEPTED`, `PARTIALLY_FILLED`, `FILLED`, `REJECTED`, `CANCELLED`, `UNKNOWN`), idempotency registry, slippage accounting, and long-only stop-loss/take-profit trigger calculation.
- `LabEngine` rejects a signal with an explicitly stale/over-age/invalid market snapshot before paper fill creation.
- `LabEngine` blocks a second BUY while a long position is already open unless the event explicitly opts into `allow_scale_in`; the default remains deny.
- Added tests for stale data rejection, duplicate BUY prevention, idempotency, partial fills, unknown order status, direction-aware slippage, and stop/target trigger calculations.
- Keeps all order operations paper-only; the order lifecycle simulator is not a broker adapter and its in-memory registry is not a durable replacement for Supabase.

## Local validation
- `python -m compileall -q .`: passed.
- `pytest -q`: 81 passed.

## Still required before live trading
1. Fix and verify the user's actual Supabase `event_seq`/restore error, V17 session heartbeat and startup recovery.
2. Run integration tests against the actual Supabase schema, including atomic event + paper-fill writes and restart replay.
3. Wire stop-loss/take-profit monitoring into the autonomous position-management loop, persist exit decisions/fills, and test daily loss/exposure limits.
4. Implement durable broker order IDs, submit/ack/fill/cancel/reconcile states, and never resubmit an `UNKNOWN` order until reconciled.
5. Test live market data freshness and actual 5-minute bars during Taiwan market hours; quantify slippage using realistic fill assumptions.
6. Complete simulated market-hour soak tests and fault injection before any separate, explicitly approved broker integration.

## Acceptance status
- Unit-level deterministic safety tests: PASS.
- Live Supabase integration and restart/fault recovery: NOT RUN in this environment.
- Real-market-hours simulation and slippage calibration: NOT RUN.
- Broker execution/live trading: NOT IMPLEMENTED; disabled by design.
