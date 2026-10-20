# AI Quant Lab V17 — Persistence Foundation

## Delivered
- Additive Supabase migration for runtime Sessions, Agent runs, checkpoints, and durable outbox.
- Database-generated `event_seq`, unique idempotency keys for event ledger and paper fills, and insert-once writes to preserve immutable event history. Added a transaction-safe SQL RPC to atomically commit a paper fill with its event; ambiguous persistence failures fail closed.
- Session lineage (`session_id`, `parent_session_id`), 30-second heartbeat, 90-second lease, stale-session detection, and duplicate-runtime blocking.
- Startup restore path: paper positions/cash rebuilt from durable paper fills; valid checkpoint restores Agent projections; post-checkpoint `agent.state_changed` events replay as state projections only.
- Agent-run lifecycle endpoints and lease-expiry recovery to `RETRY_PENDING`.
- Checkpoint hash/schema validation, API health, UI session status and manual checkpoint action.
- Persistence failure is fail-closed for starting autonomous scanning and one-shot scans.
- Preserved six original watercolor Shih Tzu agent assets; no production Tianji 3K code or `.env` included/modified.

## Validation
- `pytest -q`: 65 passed.
- `python -m compileall -q .`: passed.
- Vue `<script setup>` extracted and `node --check`: passed.
- ZIP integrity and final file exclusions checked before release.
- Supabase migration execution, actual Supabase REST permissions, Windows Vite build, and live restart/crash test still require execution in the user's environment; they are not claimed as remotely verified.

## Scope notes
- `event_seq` is monotonic but may contain gaps; gaps are expected with PostgreSQL identity sequences and retries.
- Outbox schema/primitives are present, but a real notification delivery worker is not enabled by this release.
- This is local Lab process recovery; independent Supabase backups and restore drills remain required.
