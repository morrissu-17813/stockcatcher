# Tianji 3K Production v1.2.11 — Shadow Validation (Offline, Read-only)

## Scope and safety boundary

- Add an offline shadow-validation dataset/report tool that reads existing prediction events and optional historical signal workbook.
- The tool does not import or execute the live runner, call market-data APIs, send Telegram messages, or edit source records.
- Stage 0–3 selection rules, thresholds, MIS polling cadence, API request budget, and Telegram notification flow remain unchanged.
- Missing T+5/T+15/T+30 observations remain `UNKNOWN` (or the recorded `MISSED_WINDOW`); they are never treated as negative outcomes.
- Historical workbook proxy returns are kept separate from milestone returns and are explicitly not represented as execution P&L.

## Reliability hardening included

- Use the append-only ledger as authoritative if a process interruption occurs after a `POST_SIGNAL_TRACKING_FINAL` event but before the tracking state is saved.
- Prevent post-signal samples after finalization and reconstruct missing final state after restart.
- Ensure close finalization records missing Ground Truth instead of silently omitting the prediction.

## Validation

- Shadow-validation unit tests cover read-only behavior, missing-data labels, deduplication across master/per-symbol ledger copies, and refusal to overwrite an existing report directory.
- The complete `tianji_3k/tests` suite is run against the source-only package before release.
- Full source-package regression suite: 162 passed.
- Historical 2026-10-14 workbook smoke test: 1 ledger prediction + 22 workbook signals; 9 proxy returns available (6 positive / 3 negative); T+5/T+15/T+30 remain UNKNOWN because no milestone records were present.
- This build has not been committed, pushed, or deployed.
