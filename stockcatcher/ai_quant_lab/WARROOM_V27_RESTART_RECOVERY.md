# V27 — Restart Recovery and Paper Ledger Integrity

## Scope
Additive-only isolated AI Quant Lab changes. Ground Truth remains deferred. No production Tianji 3K/TIDE code, `.env`, broker integration, live-order path, agent roles, or artwork changes.

## Changes
- Expose recovery summary in engine state: restored trade rows/fills/open positions, restored event IDs, highest event sequence, status and error.
- Restore paper fills in deterministic order: `executed_at`, then `created_at`, then `trade_key`, avoiding arbitrary replay order when market timestamps collide.
- Fail closed on duplicate persisted trade keys, missing required fill fields, or invalid restored cash/position invariants.
- Keep the existing `restore_error` startup gate; no bypass or new SQL migration.
- Add tests for open-position restore, same-timestamp buy/sell order, malformed/duplicate rows and duplicate exit-event idempotency.

## Validation boundary
Tests use fake stores and are local-only. They do not prove the configured Supabase schema/API or live-market loop is healthy. `created_at` must exist on `ai_quant_lab_paper_trades`.
