# AI Quant Lab V21 — Offline Intraday Replay & Execution Gate

## Why this version exists
V21 uses the user's 2026-10-16 Tianji 3K GitHub Actions LOG to exercise the market-day flow outside trading hours. It is additive to V20 and remains paper-only. It does not submit broker orders, alter production Tianji 3K/TIDE code, modify `.env`, or write to Supabase.

## Added

- `log_replay.py`: read-only parser for a raw `.txt` log or a `.zip` runner export. It parses Stage 0–3 metrics, final 3K pool, radar cycle counts, MIS fetch coverage, dynamic candidate events, breakout triggers, prediction evidence/levels, explicit Telegram send results, history warnings, and Ground Truth/cutoff errors. Every relevant output retains a source line number and the report includes a SHA-256 hash of the parsed log text.
- `intraday_execution.py`: reusable fail-closed entry gate for persistence readiness, market-data readiness, Taiwan local entry window, Fugle 5-minute confirmation, STRONG level, projected volume ratio, breakout price, signal/snapshot age, duplicate ticker, position count, daily loss, and cash state. Position sizing obeys the configured per-order notional ceiling and fee budget.
- Fresh-quote-only stop-loss/take-profit gate. Missing or stale exit prices do not fabricate fills.
- `run_offline_replay.py`: CLI writes Markdown/JSON reports, paper trade CSV, per-signal entry decision CSV, and a normalized audit-event JSONL.
- Tests include ZIP read-only parsing, pipeline metrics, strict order gate, duplicate signal idempotency, persistence-down fail-close, stale price/trigger gates, sizing, stop-loss/take-profit, and report output integrity.
- Included `reports/replay_2026-10-16/` generated from the user's uploaded log. The original runner log and environment dump are not bundled; the generated report retains the log-text SHA-256 and line references.
- History warning parser recognizes both `symbol=3718` and `DYNAMIC HISTORY | 3535 | ...` formats; report lists distinct affected stock codes and unidentifiable warning count.

## Replay rules (explicit assumptions)

- A paper entry is considered only when the logged prediction is `FUGLE_5M`, `STRONG`, projected volume ratio >= 2.3x, price > breakout, trigger age <= 300s, snapshot receive age <= 30s, and it is before the configured 13:20 Taiwan-time entry cutoff.
- Only one entry per symbol per replay date; default maximum 3 positions and NT$100,000 reference notional per position.
- Entry/exit execution are hypothetical full fills with 10 bps adverse slippage each side. Commission is assumed 0.1425% per side and sell tax 0.3%; these are configurable modeling assumptions, not evidence of the user's broker charges or the applicable tax for a specific account/day-trade classification.
- Exit marks use the last non-empty rendered watchlist price after entry and before 13:30. Their quote freshness cannot be proven from this LOG, so the marks and P&L are explicitly unverified proxies. The replayer does not infer intraday stop/target touches from these possibly cached display values.

## Findings from the supplied 2026-10-16 LOG

- Stage 0 complete-verification PASS=345, while Stage 1 input is 344 (one-count gap that needs production-log/source reconciliation).
- Stage 1 pass=145; Stage 2 pass=2 and fail/unknown=143; Stage 3 pass=2; final 3K pool is 4904 and 6278.
- 753 radar cycles from 09:17:46 to 13:29:48 Taipei time; maximum monitored pool=81 symbols.
- 79 distinct dynamic candidate symbols, 26 breakout-trigger events across 20 distinct symbols, 21 prediction events, and 21 explicit Telegram `SENT` records.
- Prediction levels: 19 EARLY and 2 STRONG. Evidence types: 16 MIS_LIVE and 5 FUGLE_5M.
- Strict replay assumes two entries: 3167 大量 and 4960 誠美材. The estimated net result using last rendered prices is -NT$2,447.27 (-0.2447% of NT$1m initial cash) under the assumed fees/slippage. This is **not** verified strategy performance, because no official close/complete fresh price path is present.
- Average MIS quote coverage from the logged `returned/requested` counters=11.13%; this needs investigation before treating the global snapshot as a reliable order decision source.
- Close Ground Truth failed: 16 `TypeError: 'list' object is not callable` records; cutoff says 21 predictions, 21 unavailable, 0 available. Actual accuracy is therefore not measurable from this archive.

## Validation

- V20 base tests plus V21 unit/integration-fixture tests: `pytest -q` — 96 passed in the build container.
- Python compile checks: `python -m compileall -q .` passed after the final parser/test changes.
- Real Supabase schema/REST access, startup restore after restart, Windows UI/Vite build, actual live data quote-age behavior, and broker integration: **not tested by this offline replay**.

## Go / No-Go

**NO-GO for live trading.** V21 is the offline rehearsal and audit layer. Before enabling autonomous live orders, resolve the Stage 0/Stage 1 count gap, the low MIS coverage, the Ground Truth TypeError and zero available outcomes, and the previously reported Supabase `event_seq`/startup restore error. Then pass full market-hour paper soak tests with fresh entry/exit quotes and durable order-state recovery.

## V22 animation lifecycle hotfix (2026-10-18)
- Replaced the ambient animation timer ID array with a Set of outstanding timers; fired timer IDs are removed immediately.
- Cancels ambient timers and invalidates stale sequences when the browser tab is hidden.
- Returns ambient-only Agent poses to the idle seated pose while hidden; runtime-owned motion is preserved.
- Resumes via normal refreshes when visible, without replaying missed choreography.
- Cleans up pending ambient timers on component unmount.
- Added `tests/test_animation_timer_lifecycle.py`.
- Scope remains dashboard animation lifecycle only; no trading logic, Supabase schema, `.env`, deployment, six-agent roles, or artwork changed.
