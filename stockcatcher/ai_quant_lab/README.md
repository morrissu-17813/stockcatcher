# V21 offline intraday replay (new)

This add-on replays the production runner LOG from a saved `.txt` or `.zip` without using live APIs, Supabase, or a broker. It reconstructs premarket Stage 0–3 counts, intraday radar cycles, dynamic discovery, breakouts, prediction evidence, notifications and close-verification errors; then runs a strict, hypothetical paper-entry simulation and exports an audit bundle.

```powershell
python run_offline_replay.py --log "C:\path\to\logs_tianji_3k模擬資料.zip" --out "reports\offline_replay_latest"
python -m pytest -q
python -m compileall -q .
```

The report bundled at `reports/replay_2026-10-16/replay_report.md` is produced from the provided log. It records 753 radar cycles and 21 prediction events; the close Ground Truth check failed (21/21 unavailable), so any P&L calculated from rendered watchlist marks is an **unverified scenario**, not proven strategy performance. Live-trading readiness is `NO_GO`. The original log and `.env` are not bundled.

See `WARROOM_V21_CHANGELOG.md` and `INSTALL_FIRST.txt` for the scope, limitations and safe-use notes.

---

# 天機 AI Quant Lab — Autonomous Paper Trading Milestone

This folder is isolated from `tianji_3k` and `tide-dashboard`. It does not import production Python modules, does not write to `tianji_signals`, and has no broker/live-order integration.

## What this milestone does

- Six role workers (CIO, Quant, Research, Risk, Execution, Auditor) perform visible tasks in response to actual scan/trading events. These are deterministic, auditable rule-based agents; this milestone does **not** claim that a separate LLM is connected to every role.
- Prefers Fugle authenticated intraday 1-minute candles and quote API when a Fugle key is loaded; falls back to Yahoo Finance chart API for `2330.TW`, `2317.TW`, `2454.TW`, `2382.TW`, and `3231.TW`.
- Displays price, percentage change, SMA5/SMA20, volume ratio, data timestamp/staleness, cash, equity, P&L, positions, agent tasks and event stream.
- Autonomous loop is **OFF by default**. The user must click **啟動自主研究**. It scans the watchlist on a conservative interval. Starting autonomous scans and trade-producing one-off scans are blocked unless Supabase server-side persistence is configured.
- Baseline strategy: enter only when latest price > SMA5 > SMA20; exit on price below SMA5 or 2% drawdown from average cost. Per-order notional is capped at NT$100,000 by the engine. This is a test strategy, not a return guarantee.
- If market data is missing or older than 20 minutes, it is marked stale and will not trigger a trade. This intentionally means no automated trades from old market-close prices when the exchange is closed.
- Supabase is the only durable store. The only allowed write tables are `ai_quant_lab_events`, `ai_quant_lab_paper_trades`, and `ai_quant_lab_reports`. If server-side credentials are absent, the app displays memory-only mode and trades will not survive restart.

## Run locally

Requires Python 3.10+ and Node.js/npm for the Vue dashboard; no third-party Python package is required.

**Windows (recommended):** run `START_LAB_WINDOWS.ps1`. It opens the backend API in one PowerShell window and the actual Vue/Vite dashboard in another, then opens `http://127.0.0.1:5173/`. The script installs dashboard dependencies only if the required chart package is missing.

**Manual start (two terminals):**

Terminal 1 — backend API:

```powershell
cd stockcatcher/ai_quant_lab
python server.py
```

Terminal 2 — frontend:

```powershell
cd stockcatcher/ai_quant_lab/dashboard
npm install
npm run dev -- --host 127.0.0.1
```

Open `http://127.0.0.1:5173/` for the interactive Vue dashboard. The API remains at `http://127.0.0.1:8765/`. If you run `npm run build` in `dashboard`, the backend also serves `dashboard/dist` at port 8765; until a build exists, its root route keeps the older standalone preview as a backwards-compatible fallback.

The backend attempts to load the existing `.env` from the repository layout including `stockcatcher/stockcatcher/.env` (and never prints secret values). Check `/api/health` for key-presence booleans only. Set these backend environment variables to enable Supabase persistence:

- `SUPABASE_URL=https://<your-project-ref>.supabase.co`
- `SUPABASE_SERVICE_ROLE_KEY=<server-side secret>`

Never put the service role key in the frontend, source control, screenshots, or chat. Do not use the publishable/anon key for these RLS-protected writes. Do not enable public RLS policies for these tables.

## API

- `GET /api/health`
- `GET /api/state`
- `GET /api/market`
- `POST /api/autonomy/start`
- `POST /api/autonomy/stop`
- `POST /api/autonomy/scan-once`
- `POST /api/demo` (explicit test trade with manually supplied price; clearly not market-priced)
- `GET /api/report`

The server binds to `127.0.0.1` only. No deployment or external exposure is configured.

## Limitations / honest status

- Yahoo Finance public chart API is not a guaranteed exchange-grade real-time feed; availability, delay and rate limits may vary. The app shows source and candle timestamp.
- The current development container had no accessible `.env` and external provider connectivity could not be validated, so real Fugle/Yahoo fetch could not be verified here. Verify from the user's local machine; failures are surfaced and do not generate trades.
- The six roles are real task handlers with state transitions, but LLM-based autonomous web research is not connected in this milestone. The market feed is public chart data only, not news research.
- Supabase persistence is enabled only when the server-side secret is configured. Never claim persistence based on mock tests alone.
- No local SQLite or JSONL application-state persistence is used. Reports are written to Supabase only.

## Reliability improvements in this build

- The market adapter now ties the displayed market timestamp to the latest usable candle, avoiding an incomplete trailing candle making a quote look newer than it is.
- If a refresh fails, any previously displayed quote is explicitly marked stale and carries a refresh error; it cannot silently remain presented as current.
- Manual scans and background scans share a non-blocking cycle lock to prevent overlapping scans from creating duplicate paper orders.
- The engine serializes state-changing events and protects dashboard snapshots from concurrent writes.
- Supabase paper-trade restore pages through records in 1,000-row batches instead of silently restoring only the first 1,000 fills.

## Validation for this build

- Python unit tests: 21 passed.
- Local HTTP smoke tests: `/api/health` and `/api/state` returned HTTP 200; six agent roles were present.
- A real scan endpoint request ran against the configured public provider, but this development environment could not resolve the external Yahoo host. All five symbols correctly returned `data_error`; no fake-price trades were created. Live-data access must be verified on the user's local network.
- Supabase persistence contract tests use a test double. Real writes still require a server-side Supabase secret and a local connectivity test.

## Hybrid war-room visual update

- The six office characters now use full-body watercolor Shih Tzu sprites with role-specific coat/accessory designs; CSS choreographs sit/observe/stand/walk-to-console/report/return-to-desk routines instead of shaking a portrait in place.
- Workstation screens have subtle independent telemetry animations. These are ambient UI effects only and do not fabricate market prices, agent work, or fills.
- Real Agent statuses from `/api/state` override ambient choreography: working, warning and success poses are driven by runtime status/task transitions.
- Responsive layout supports desktop and mobile widths; `prefers-reduced-motion` is respected.
- The server loads a neighboring `stockcatcher/.env` (the `stockcatcher/stockcatcher/.env` path in the repository layout) without overriding process environment variables, and health output reveals only whether key groups are configured, never their values.
- Important: key detection is not the same as provider integration. This milestone's quote adapter is still Yahoo Finance; Fugle/FinMind provider routing and Telegram notification delivery require separate adapter implementation and live credential verification. Supabase writes still require the server-side service-role key and successful connectivity.


## Tonight's connectivity and live-data update

- Added a Fugle REST adapter (`X-API-KEY`) for intraday 1-minute candles and current quote, preferred whenever a Fugle key is configured. Yahoo remains a labelled fallback only.
- Fixed daily change display to use `change_pct` consistently.
- Added a true equity-history sparkline built from observed ledger equity snapshots (no generated market prices).
- Added server-side Telegram notification for successful paper fills only. Telegram failures are reported without exposing tokens.
- Expanded `.env` path discovery to cover `stockcatcher/stockcatcher/.env` and common repository placements.
- Autonomous and scan-once endpoints now fail closed when Supabase persistence is not configured, preventing unattended paper fills from silently disappearing on restart.
- Added adapter tests for Fugle response mapping, missing credentials, empty candles and provider selection.
- Validation in this build: 25 Python tests pass; HTTP health/state/market smoke tests pass. npm dependency installation timed out in this isolated environment, and real provider/Supabase/Telegram connectivity cannot be claimed until run on the user's machine with its `.env`.


## Reused Tianji 3K intraday monitoring design (isolated copy)

- `tianji_radar.py` is a Lab-local, read-only adapter based on the existing production monitoring design; it does not import or edit `tianji_3k/`.
- Universe metadata is loaded from TWSE OpenAPI `STOCK_DAY_ALL` and TPEx OpenAPI `tpex_mainboard_quotes`, cached for six hours.
- Every radar cycle reads batched TWSE MIS snapshots, preserving last-trade time, data age, source, and cumulative volume in lots. Missing/old quotes are marked stale and excluded from discovery.
- Dynamic Discovery mirrors the production candidate gate (previous-day volume >= 1,000 lots, up >= 3%, price above open, current volume >= 300 lots, normalized volume pace >= 0.8). It is explicitly `DYNAMIC_CANDIDATE_NOT_3K_PASS`.
- This first integration is **discovery-only**. It does not yet promote dynamic candidates to paper orders. Candidate-to-state-machine/Fugle 5-minute confirmation and projected-volume checks must be wired and tested before those candidates can influence paper trading. Existing five-symbol Lab strategy remains separately guarded by stale-data and Supabase checks.
- The Lab radar poll interval defaults to 20 seconds. No changes were made to the production `tianji_3k/` or `tide-dashboard/` files.


## Full Tianji-style confirmation chain (v5 development)

The Lab-local autonomous entry path now follows this sequence:

1. TWSE/TPEx OpenAPI universe metadata and batched TWSE MIS snapshots.
2. Dynamic candidate gate (candidate only; never treated as 3K PASS).
3. Selective FinMind daily-history enrichment for up to three candidates per cycle; uses completed daily bars only, requires 61+ bars, Stage-1 trend, and VMA5 >= 1,000 lots.
4. Isolated copy of the Tianji state-machine semantics: effective breakout above the prior two-day high plus 0.3%, gain >= 4%, and two distinct MIS data identities.
5. Fugle completed 5-minute bars: at least 23 completed bars; third bar close must exceed the prior two highs AND its volume must be >= 1.2x the preceding 20-bar baseline. Pending confirmations retry for up to 300 seconds.
6. Projected full-session volume must be ready (at least five minutes elapsed) and >= 1.5x VMA5.
7. Paper risk gate checks existing position, available cash, per-order notional cap, and Supabase persistence configuration. Successful fills are persisted only to the three dedicated AI Quant Lab Supabase tables and may send a Telegram paper-fill notice.
8. Fresh MIS quotes can trigger a 2% paper stop-loss exit; stale quotes never trigger entries or exits.

The former SMA5/SMA20 watchlist loop is now display-only and cannot independently create paper buys. This prevents a shortcut strategy from bypassing the requested confirmation chain. All live orders remain disabled.

The dashboard's confirmation-chain panel shows per-candidate states, reasons, 5-minute confirmation, projected volume, and paper fill result.

### v5 validation boundary

- Python unit tests cover distinct-snapshot gating, history/5m failure paths, projected-volume thresholds, Supabase gating, and paper-fill persistence contract.
- These tests use fixtures/test doubles for the trade path. They do not prove live Fugle, FinMind, Supabase, Telegram connectivity.
- The current environment does not contain the user's private `.env`; live provider and Supabase write tests must run on the user's computer.
- Production `tianji_3k/` and `tide-dashboard/` remain untouched. The Lab's copied state machine and adapters live entirely under `ai_quant_lab/`.

### Agent office movement (v7)
The office characters are driven by backend Agent state transitions. Each transition publishes a compact `agent.state_changed` event into the existing `ai_quant_lab_events` table, including `agent_id`, `status`, `task`, `target_zone`, and `bubble`. The dashboard consumes the current role state through the local Lab API and animates the character to the corresponding room zone. This intentionally reuses the existing Supabase schema instead of creating a separate `agent_logs` table; the service-role key remains backend-only. UI telemetry failures never bypass or alter paper-trading risk checks.


## V11 Market Terminal update
- Adds cached `/api/benchmarks` endpoint for Taiwan Weighted Index, OTC Index and USD/TWD via Yahoo Finance chart API. Each item reports `ok`, source and an explicit error when unavailable; cached for 60 seconds to reduce requests.
- Uses TradingView Lightweight Charts for intraday line / OHLC candlestick views from the existing `/api/market` market candles.
- Displays a 3K marker only when the selected symbol has a corresponding backend confirmation state (`breakout_triggered`, confirmation pending, or paper buy). It marks the latest returned candle, not an independently backtested historical breakout.
- Benchmark API and external provider connectivity must be verified on the user's machine; index/FX provider may fail independently. No fake quote fallback is shown.

## V12 War Room visual rebuild

See [WARROOM_V12_VISUAL_REBUILD.md](WARROOM_V12_VISUAL_REBUILD.md) for the market-terminal/illustrated-office redesign, chart indicators, provider semantics, and validation notes. The lower office uses a dedicated watercolor room background while preserving the six original transparent Agent sprites and live API-driven movement.


## V13 — monitoring logs, cache-first history, ToAlpha research

- `監控記錄` appears directly under the watchlist and shows bounded live Action logs from the actual autonomy loop: start/stop, cycle boundaries, MIS snapshot counts, dynamic candidates, history checks, quote refreshes and errors. It polls the same `/api/market` status used by the existing UI; it does not create fake market events.
- Technical K-line mode requests `GET /api/market/history?symbol=2330`. The API first reads `../tianji_3k/cache/daily/TaiwanStockPrice_<symbol>_*.json`, then requests history only if fewer than 60 completed bars exist. FinMind is preferred when its token is configured; Yahoo daily chart is the labelled fallback. Daily volume remains in source share units for display. Intraday mode continues to use the existing intraday quote adapter.
- The `AI 台股研究工具` panel discovers ToAlpha tools via `GET /api/research/tools` and calls a selected tool through `POST /api/research/call`. MCP traffic stays server-side; no endpoint credentials are exposed to the browser. Tool output is shown as returned JSON with errors shown explicitly. This is a direct tool console, not an LLM-generated analysis feature.
- The source includes a targeted fix for the extra `}` in the radar price interpolation.

### V13 verification status
- Python compileall: passed.
- Unit tests: 40 passed.
- Vue SFC parse and template compilation: passed.
- Full Vite production build not verified in the build container because the archived `node_modules` is missing the Linux Rollup optional binary and npm registry DNS is unavailable. On Windows, run `npm install` then `npm run build`.
- Live ToAlpha MCP, FinMind/Yahoo daily history and the sibling production cache are runtime integrations and must be checked on the local machine/network.


## V14 development — research-first autonomy foundation

- The ToAlpha research form now builds tool arguments from each tool's schema using normal form fields. Raw JSON output and JSON parameter textarea are removed from the user-facing page; nested result values are rendered as readable text.
- Added a read-only Tianji 3K prediction feed adapter. It looks for `TIANJI_3K_DATA_ROOT` or a nearby `tianji_3k` directory and reads prediction/validation ledgers without writing to production. The production event schema has now been checked against the provided 2026-10-16 runtime archive. Imported events are still audit-only and are **not** directly converted into orders.
- Added `/api/production/signals` for the signal bridge panel. The API reports missing paths clearly and fails closed.
- Added `/api/backtest?symbol=2330` and a readable backtest report panel. It uses completed daily bars, a 3K-style filter, next-session-open entries, 2% stop-loss, a five-bar maximum holding period, and estimated fees. This is an initial explicit simulation specification, not yet a verified replica of every production intraday rule; slippage, limits and exact exit logic require calibration.
- Backtest reports are persisted to `ai_quant_lab_reports` only when Supabase is configured. No production files are modified and no broker/live orders are supported.
- Tests: 45 passed. Python compileall passed. This environment lacks `node_modules`, so the Vue/Vite production build still needs to be verified on Windows using `npm install` and `npm run build`.

### Remaining inputs before enabling true six-Agent autonomous trade research

1. Verify that auto-discovery finds the local `tianji_3k` directory; otherwise set `TIANJI_3K_DATA_ROOT` in the existing `.env`. The provided runtime archive verified the prediction/notification/validation event schema, but live local path and current-day Ground Truth availability still need runtime confirmation.
2. Configure an AI provider in the existing `.env` for autonomous LLM reasoning. Do not paste secrets into chat. The current ToAlpha MCP integration is a tool-call interface; it does not by itself provide an LLM reasoning model or mean six independent LLM agents are already running.
3. Confirm the exact production exit rules and sizing assumptions for backtests (the current report explicitly uses a 2% stop and up to five daily bars as provisional assumptions).

## V15 — Production prediction audit bridge

- Adds a read-only reconciliation view for real `INTRADAY_3K_PREDICTION`, `NOTIFICATION`, and `PREDICTION_VALIDATION` rows keyed by immutable `prediction_id`.
- Separates the prediction's notification gate (`READY`/`MOMENTUM`) from the actual Telegram delivery status (`SENT`/other status). A notification is counted as sent only when a durable `NOTIFICATION` event says so.
- Reports missing Ground Truth explicitly; unavailable outcomes are never counted as hits or failures and no intraday price path is inferred from a daily 3K flag.
- Adds an explicit Supabase audit import action. It imports prediction and validation events into the Lab event ledger only when Supabase is configured. It never writes to Tianji 3K and never creates paper orders.
- The dashboard keeps the existing six watercolor Shih Tzu agents and office assets; this release only extends the existing production-signal section.

### V15 API

- `GET /api/production/audit?since=YYYY-MM-DD`: pair predictions and validations by `prediction_id`, and reconcile actual notification delivery events.
- `POST /api/production/import` with optional `{"since":"YYYY-MM-DD"}`: explicitly import read-only audit events into Supabase; fails closed when Supabase is not configured. Paper orders created: always `0`.

### Known boundary

The 2026-10-16 production archive contains 21 prediction events, 21 durable `NOTIFICATION` events with `notification_status=SENT`, and 21 validation events with `GROUND_TRUTH_UNAVAILABLE_AT_CUTOFF`; there are no `ground_truth.json` snapshots for that day. Thus delivery is confirmed, but prediction accuracy is not. True post-signal MFE/MAE and execution-path replay requires historical intraday candles/ticks and is not fabricated in this version.

## V16 — Evidence-first six-Agent decision journal

- Adds `decision_journal.py`: each audited production `prediction_id` creates six distinct role records (CIO, Quant, Industry Research, Risk, Paper Execution, Auditor) with source evidence, risk flags, unknowns, and next verification step. The records are rule-based and explicitly state when Ground Truth, fundamental sources, or post-signal intraday paths are missing.
- Adds `GET /api/production/decisions?since=YYYY-MM-DD&limit=50` for preview and `POST /api/production/decisions/generate` for explicit Supabase persistence. Persistence fails closed when Supabase is not configured. Every generated record uses a stable decision ID for deduplication; no production writes and no paper orders are created.
- ToAlpha MCP research calls now produce an `agent.research_evidence_recorded` event in the Lab ledger, including tool name, arguments, result hash, timestamp, Agent, and result (truncated with a hash if large). The MCP result is still an external-source response, not automatically a verified conclusion.
- Adds optional `POST /api/agents/gemini-review` with `{"prediction_id":"..."}`. When `GEMINI_API_KEY` exists in the existing local `.env`, Gemini reviews the fixed signal evidence packet and must return a structured critique (supported points, unverified hypotheses, missing evidence, contradictions/risks, suggested checks). Its output is marked advisory-only and persisted as a research-evidence event; it cannot override hard risk rules or create orders. Set `GEMINI_MODEL` optionally; default is `gemini-2.5-flash`. No secret values are returned to the frontend or logs.
- Dashboard adds preview/persist controls for the six-Agent decision journal and an optional Gemini review action. The six original watercolor Shih Tzu assets and office scene are retained.
- Engine now records MCP/Gemini evidence events in the same Supabase event ledger. The only durable storage remains the existing Lab Supabase tables; no schema migration is required.
- Safety boundary: this is still isolated paper-only research; no broker integration, no live orders, and no writes into Tianji 3K production data.

### V16 verification
- `pytest -q`: 51 passed.
- `python -m compileall -q .`: passed.
- Vue `<script setup>` JavaScript syntax (`node --check`): passed. Full Vite build still needs local Windows verification because `node_modules` is not included in the package.
- Against the provided 2026-10-16 runtime archive: 21 production predictions, 21 confirmed Telegram SENT events, 0 available Ground Truth; V16 generated 21 journal packets / 126 Agent records in read-only preview. This confirms delivery evidence, not prediction accuracy.
- Gemini network call and ToAlpha MCP connectivity remain dependent on local network/provider credentials and were not claimed as live-tested here.

## V17 — Persistence Foundation (Session / Recovery / Idempotency)

V17 adds durable runtime sessions and recovery controls to the isolated AI Quant Lab. It does not modify the Tianji 3K production tree and does not enable broker/live orders.

### Before first V17 launch

1. Back up the existing AI Quant Lab Supabase project.
2. Open Supabase Dashboard → SQL Editor and run `supabase/migrations/202610170001_v17_persistence_foundation.sql` once. The migration is additive and expects the existing V16 tables `ai_quant_lab_events`, `ai_quant_lab_paper_trades`, and `ai_quant_lab_reports` to exist.
3. Keep the existing backend-only `.env` and confirm `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` are set. Never place service-role keys in Vue or browser code.
4. Start the Lab and check `GET /api/health`, `GET /api/persistence`, and `GET /api/state`. Autonomous scanning stays blocked unless V17 can establish a durable Session and complete startup recovery.

### V17 persistence contracts

- `ai_quant_lab_events.event_seq` is a database-generated monotonic sequence (gaps are expected; it is not a gapless counter). `idempotency_key` is unique and existing event keys are backfilled.
- Events and paper fills use insert-once semantics; replaying the same event key must not rewrite the original event or create a second paper fill. New paper-fill commits use the transactional `ai_quant_lab_commit_event` RPC so event + fill are committed together; ambiguous persistence failures mark the engine degraded and stop autonomous cycles.
- `ai_quant_lab_sessions` records each runtime Session and its parent Session. Heartbeats run every 30 seconds; the lease default is 90 seconds. A fresh heartbeat from another runtime blocks a second instance to avoid split-brain execution.
- `ai_quant_lab_agent_runs` stores task status, attempt count, input event IDs, lease, error and result. Expired `RUNNING` / `WAITING_EXTERNAL` tasks are marked `RETRY_PENDING` during recovery; this does not automatically execute them without an idempotent worker.
- `ai_quant_lab_checkpoints` stores a versioned JSON state and SHA-256. Invalid hashes and unsupported schema versions are ignored. Current snapshots restore Agent role projections; cash and positions are reconstructed from the paper-fill ledger, while post-checkpoint Agent state events are replayed as projections only (never re-executing trades).
- `ai_quant_lab_outbox` is the durable schema for idempotent side effects. V17 provides enqueue/query/update primitives; a production notification dispatcher and delivery reconciliation remain separate work and must not be assumed active merely because the table exists.
- `/api/persistence` exposes runtime/session/checkpoint health. `POST /api/persistence/checkpoint` creates a checkpoint. `POST /api/agent-runs/start` and `POST /api/agent-runs/{run_id}/finish` provide durable Agent-run lifecycle endpoints.
- If Supabase/schema/recovery/heartbeat is unavailable, the runtime marks persistence degraded and blocks new autonomous cycles. It does not pretend that in-memory state is durable.

### Recovery boundaries

This is crash recovery for the local Lab process, not a guarantee against loss of a Supabase project without independent backups. Continue scheduled database backups and periodically test restoration. A graceful shutdown marks the session `CLOSED`; an ungraceful shutdown is recognized after its heartbeat lease expires and then marked `CRASHED` on the next start.


## V18 Durable Notification Dispatcher

V18 routes paper-fill notifications through the Supabase transactional Outbox instead of sending synchronously in the autonomy loop. Apply V17 migration first, then `supabase/migrations/202610170002_v18_durable_notification_dispatcher.sql`. See `WARROOM_V18_CHANGELOG.md` and `INSTALL_FIRST.txt`. Runtime health is available at `GET /api/notifications/status`. Delivery is at-least-once with an explicit `UNKNOWN` state for ambiguous Telegram outcomes; no exactly-once guarantee is claimed.

## V19 signal validation and refresh continuity

- Run the API as before with `python server.py`; run the dashboard with `cd dashboard` then `npm ci` / `npm run dev`.
- In V16 decision journal, use **「驗證台表科 6278（10/7）」** to calculate a daily-bar-only post-signal review for signal date `2026-10-07`, reference price `250.5`, 7 subsequent trading bars, and a hypothetical 2% stop. It never places an order and never writes to Tianji 3K production data. If Supabase is configured, the report is saved as a Lab-owned `SIGNAL_POST_VALIDATION` report; otherwise the UI explicitly indicates it was not persisted.
- After a successful validation, **「Gemini 覆核事後結果」** sends that fixed report as evidence for a second advisory review. The endpoint requires a healthy durable V17 session before calling Gemini, saves a separate evidence event, and does not overwrite the first review.
- On refresh, the UI restores lightweight display state and recent research outputs from browser `localStorage`; the backend and Supabase remain authoritative for engine/session/ledger state. Browser storage is not a trade ledger.
- When the dashboard tab is hidden, UI polling and ambient choreography pause; the backend's own autonomy/session process is not stopped by a browser refresh.

## V20 Execution Safety Foundation

See `WARROOM_V20_CHANGELOG.md`. The additive `execution_safety.py` module provides broker-free paper order lifecycle, idempotency, market-data freshness, slippage and stop/target calculation primitives. The engine now rejects explicitly stale market snapshots and duplicate long entries by default. This is not live-trading support; durable broker reconciliation, position-exit automation, daily-loss limits, live Supabase recovery and market-hours soak tests remain required.

## V21 — offline replay of the Tianji 3K runtime LOG

V21 adds `log_replay.py`, `intraday_execution.py`, and `run_offline_replay.py`. It can run outside market hours on a saved GitHub Actions LOG (`.txt` or `.zip` export), then write a decision audit and broker-free paper scenario. It is intentionally not wired to a broker. The bundled report is in `reports/replay_2026-10-16/` and reflects only the uploaded LOG.

Run from this directory in PowerShell:

```powershell
python run_offline_replay.py --log "C:\path\to\logs_tianji_3k模擬資料.zip" --out "reports\offline_replay_latest"
```

Then open `reports\offline_replay_latest\replay_report.md` for the summary. Other outputs are `replay_report.json`, `paper_trades.csv`, `entry_decisions.csv`, and `audit_events.jsonl`. No Supabase connection or network API is called by this offline replay command.

Run the complete test suite:

```powershell
python -m pytest -q
python -m compileall -q .
```

Important: `paper_trades.csv` is a replay assumption, not real order/transaction data. The script deliberately labels the last rendered watchlist price as an unverified mark when the source does not contain complete, timestamp-verified intraday price paths. For V21 scope and blockers, see [WARROOM_V21_CHANGELOG.md](WARROOM_V21_CHANGELOG.md).
