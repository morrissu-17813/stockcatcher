# V23 Paper Ledger Replay Correctness

## Scope
Minimal, isolated AI Quant Lab change. No production Tianji 3K/TIDE code, `.env`, Supabase schema, Agent artwork/roles, broker connection, or live-order path changes. Ground Truth remains deferred.

## Changes
- Include buy-side commission in average-cost basis, so realized/unrealized P&L reconciles with cash and marked holdings.
- Add `fee_override` only for deterministic replay of persisted paper fills; new simulated fills still calculate fees from configured `fee_rate`.
- Supabase restore reads the existing `fees` column and replays each historical fill using its persisted commission rather than the current runtime fee configuration.
- Add regression tests for commission accounting, negative fee rejection, and historical-fee replay after configuration changes.

## Safety
- Paper-only execution remains unchanged; no broker integration or live order endpoint added.
- No Supabase migration is required; the existing `ai_quant_lab_paper_trades.fees` column is reused.
- Supabase startup/recovery remains fail-closed. This release does not bypass the unresolved `event_seq` schema/API error.

## Validation
Run `python -m pytest -q` from this folder. Live Supabase restore remains unverified until tested against the configured project.
