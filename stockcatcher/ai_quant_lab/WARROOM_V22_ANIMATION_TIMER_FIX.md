# V22 Animation Timer Lifecycle Fix

## Scope
Minimal dashboard-only correction based on V21. No trading strategy, Agent roles, dog artwork, Supabase schema, credentials, deployment, or `.env` changes.

## Changes
- Track outstanding ambient animation timeout IDs in a `Set` instead of an ever-growing array.
- Remove each timeout ID from the set as soon as its callback fires, including callbacks that exit early.
- When the document becomes hidden, cancel pending ambient timeouts and invalidate each Agent's current ambient sequence. Ambient-only poses return to `sit`; runtime-owned motions are not overwritten.
- When the document becomes visible, refresh the UI from the existing backend flow. The ambient interval continues naturally; there is no catch-up animation burst.
- On component teardown, clear pending timers and invalidate ambient sequences.

## Safety boundary
Ambient choreography remains presentation-only. It does not dispatch Agent tasks, call trading endpoints, or create orders. The six existing Agent roles and image assets are unchanged.

## Validation
Run the dashboard production build and Python tests from the project root. This patch was designed as a lifecycle/memory-reference fix; browser profiling over a long session is still required to measure real-world memory usage.
