# AI Quant Lab V13 change log

Base: user's uploaded local working version `ai_quant_lab_本地紀錄.7z` (not an older generated ZIP).

## Changes
- Fixed the extra closing brace in the full-market radar row (`formatRadarPrice(c.price)` Vue interpolation).
- Added bounded live monitoring log records to the autonomous loop and `/api/market` status. Records cover start/stop, cycle start/end, TWSE/TPEx MIS snapshot counts, dynamic candidates, cache/API daily-history checks, quote refresh, and provider errors. UI displays `監控記錄` directly under `監控股池`, with all/signal/error filters.
- Added cache-first daily history endpoint `/api/market/history?symbol=...`. Reads sibling `../tianji_3k/cache/daily/TaiwanStockPrice_<symbol>_*.json`; only when fewer than 60 usable completed daily bars are found does it request FinMind (if token configured), otherwise Yahoo Finance daily chart fallback. Results are merged/de-duplicated and cached in memory for 10 minutes. Technical candle mode uses daily history; intraday mode continues using the live provider's intraday bars.
- Added a ToAlpha Streamable HTTP MCP research panel. Backend discovers tools with `tools/list` and invokes selected `tools/call` tools. No secret is placed in frontend. The panel exposes tool schema parameter names, JSON arguments, result, and explicit connection errors. MCP connectivity was not verified from this offline build environment.
- Kept the existing paper-only trade pipeline and existing six Agent sprites. No production Tianji 3K logic was edited.

## Validation
- Python compileall: passed.
- pytest: 40 passed.
- Vue SFC parse + template compilation with `@vue/compiler-sfc`: passed.
- Full Vite production build could not run in this Linux container because the uploaded `node_modules` contains a platform-incompatible/missing optional Rollup package (`@rollup/rollup-linux-x64-gnu`) and network access to npm registry is unavailable. Run `npm install` then `npm run build` on Windows.
- Live ToAlpha MCP, FinMind/Yahoo history fallback and actual sibling `tianji_3k/cache/daily` contents require validation on the user's machine/network.

## V13.1 — Research tool cards and full Agent labels
- Added `/api/agents/research` as an Agent-facing backend tool-call endpoint; accepts an Agent ID, ToAlpha MCP tool name, and object arguments, and reflects running/success/failure status into that Agent's task state.
- Manual research calls now delegate through the selected Agent, and results render as compact data cards or a horizontally scrollable table. Raw JSON remains available only inside a collapsed troubleshooting disclosure.
- Kept the advanced arguments JSON editor, but moved it to an explicitly labeled advanced field so it is no longer the main output experience.
- Fixed clipped Agent names in the office floor labels and progress list by allowing wrapping and showing full display names.
- Preserved all six existing Shih Tzu sprite assets, existing Supabase persistence, paper-only trading, and production Tianji 3K/TIDE separation.
