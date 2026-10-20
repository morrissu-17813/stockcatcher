# AI Quant Lab — Hybrid War Room v1

Baseline: `tianji_ai_quant_lab_autonomous_milestone_v2.zip` (21-test backend baseline).

## Scope
- Updated only the isolated Lab dashboard and added the Agent avatar assets/design references.
- Preserved v2 backend modules (`server.py`, `autonomy.py`, `engine.py`, `market_data.py`, `supabase_store.py`, `paper_trading/`, `event_adapter/`) to avoid inheriting backend regressions from the separate War Room v4 experiment.
- Added responsive hybrid layout: top market/portfolio strip, central market board, six-agent office floor, event stream, task status, paper ledger, control bar.
- Agent ambient motion is explicitly visual-only. Runtime states/tasks still come from Lab API.
- Replaced the prior illustrative main chart path with a path derived from the latest returned quote candles. When no valid candle data exists, the chart shows a waiting state instead of inventing a price curve.
- Corrected quote percentage field to `change_pct`, as returned by the v2 market adapter.
- Kept the backend loopback-only, paper trading only, Supabase adapter unchanged, and no edits to production Tianji 3K/TIDE Dashboard.

## Verification
- Python unit tests: 21/21 passed.
- Live quote probe for `2330.TW`: blocked in this execution environment by DNS resolution (`Temporary failure in name resolution`). Live market-data correctness therefore remains unverified here.
- Frontend build: `npm install` exceeded the execution time limit, so a Vite production build could not be completed in this environment.
- Real Supabase read/write: not verified because server-side Supabase credentials were not present in this environment. Configure `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` in the local/server environment only; do not place secrets in the frontend or paste them into chat.

## Run
See `README.md`; start the API and Vite dashboard separately. The API defaults to `127.0.0.1:8765` and Vite to `127.0.0.1:5173`.

## v7 — Event-driven Agent choreography (2026-10-17)
- Applied the supplied Gemini pattern to the existing AI Quant Lab architecture: backend Agent state transitions now carry `agent_id`, `status`, `task`, `target_zone`, and `bubble`.
- Persisted movement/state events through the existing `ai_quant_lab_events` table. No `agent_logs` table was added, preserving the dedicated Supabase schema and allowlist.
- Dashboard maps backend `target_zone` values to room coordinates and animates each Shih Tzu across the shared office floor; task text appears as the character's speech bubble. Status affects movement destination and animation.
- Existing paper-trading safety, market confirmation chain, Supabase-only persistence, and Tianji 3K/TIDE production modules remain unchanged.
- Validation: Python tests pass (35/35). Frontend production build was not verified because dependency installation timed out in this environment.
