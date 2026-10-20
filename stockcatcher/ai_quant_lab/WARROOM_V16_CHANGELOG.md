# AI Quant Lab War Room V16 — Evidence-first Agent Decisions

## Purpose
Move from decorative Agent activity to a traceable research and decision record grounded in production signals, validation, and explicit risk limits.

## Changes
- Six role-specific records per real audited prediction ID, with evidence fields, source path, unknowns, risk flags, and next steps.
- Read-only preview API plus explicit Supabase persistence API; stable decision IDs; fails closed without Supabase.
- MCP tool calls are recorded as external research evidence with arguments, timestamp, result hash, Agent and bounded result payload.
- Optional Gemini structured evidence critique using `GEMINI_API_KEY` and optional `GEMINI_MODEL`; advisory only, no order authority.
- Dashboard adds decision journal preview/persistence and Gemini review controls.
- No production tree writes, no broker connection, no live orders, no paper orders from imported prediction events.
- Existing six watercolor Shih Tzu assets and office visuals retained.

## Endpoints
- `GET /api/production/decisions?since=YYYY-MM-DD&limit=50`
- `POST /api/production/decisions/generate` with optional `since` and `limit`
- `POST /api/agents/gemini-review` with `prediction_id`
- Existing `POST /api/research/call` and `/api/agents/research` now leave a durable evidence envelope in the Lab event ledger when Supabase is configured.

## Verification
- 51 tests passed.
- Python compileall passed.
- Extracted Vue script passed `node --check`.
- Runtime archive check: 21 signals -> 21 journal packets -> 126 Agent records; Ground Truth remains unavailable for all 21.
- Full Vite build and live Gemini/MCP connectivity need local Windows/network verification.
