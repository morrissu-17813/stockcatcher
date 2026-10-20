# V29 — End-to-End Paper Exit Verification

## Scope
V29 adds integration-style tests around the existing V28 automatic position monitor and real `LabEngine` exit-processing path. It does not alter production Tianji 3K/TIDE, `.env`, Supabase schema, broker connectivity, or live-order capability. Ground Truth remains deferred.

## Verified in local tests with a durable-store test double
- A fresh MIS-like stop-loss quote flows from `AutonomousLoop._monitor_open_positions` through `LabEngine.process`, updates the paper ledger, and reaches the durable commit boundary.
- Take-profit uses the same path and records `TAKE_PROFIT`.
- Stale quotes do not close positions.
- A simulated durable commit failure rolls the in-memory ledger back and marks persistence degraded.
- Replaying the same quote identity does not create a second fill.

## Important boundary
These are integration-style tests using a fake durable store, not a live Supabase or live MIS acceptance test. The system remains paper-only. Real project schema, permissions, network outages, background-thread restart behavior, and a live-market soak test still need verification against the configured environment.
