# War Room V12 — Visual Rebuild

## What changed

- Replaced the accumulated V8–V11 CSS override stack with one coherent terminal and office visual system.
- Reordered the primary screen: global market cards first, chart-led trading terminal next, the live watchlist and event stream at the right, then the illustrated office with the six original Agent PNG sprites.
- Added a dedicated Japanese watercolor office background asset at `dashboard/public/office/office-floor.webp`. This is only a room/furniture background; live market values, the chart, watchlist, events, and Agent sprites remain live HTML/UI elements.
- Reduced the prominence of individual desk cards and made the original Agent sprites significantly larger; agents continue to move using existing Lab state and choreography.
- Made the technical candlestick chart the default view. Candles mode overlays MA5/10/20/60 and volume histogram, built from up to 240 returned one-minute candles. The intraday line mode remains selectable.
- Added seven benchmark cards: Taiwan Weighted, TPEx, USD/TWD, Nikkei 225, KOSPI, Nasdaq-100 futures, and PHLX Semiconductor futures (SXF). The six Yahoo Finance chart requests run concurrently and are cached for 60 seconds; SXF uses TAIFEX's official daily futures report and is explicitly labeled as a daily report, not tick-by-tick real-time data.
- Benchmark sparkline paths use provider-returned history; a missing market feed remains visibly unavailable rather than displaying fabricated prices.
- Preserved the existing isolated paper-trading controls, API contracts, Supabase persistence, event flow, and six approved Agent sprites. No production Tianji 3K files were edited.

## Important data semantics

- 3K markers currently show the confirmation status against the **latest available K bar**, because the confirmation rows do not yet persist the exact breakout candle timestamp/price. The UI labels this limitation instead of claiming a historical timestamp.
- `SXF` is fetched from TAIFEX's daily report endpoint; this data is not a tick-by-tick streaming feed. If the official report is unavailable, its card will explicitly show unavailable.
- Market data depends on external provider reachability and coverage. No API success was verified in the coding container.

## Validation

- `python -m compileall -q .` — passed.
- `pytest -q` — 38 passed.
- JavaScript `<script setup>` parse check with `node --check` — passed.
- CSS parse check with PostCSS — passed.
- Browser screenshot smoke test could not complete because headless Chromium hung in this container; visual browser verification remains pending.
- Vue/Vite production build — **not verified**: npm registry DNS requests failed with `EAI_AGAIN` in the build environment, so `npm install` could not complete. On Windows, run these inside `ai_quant_lab\dashboard`:

```powershell
npm install
npm run build
```

The frontend declares `lightweight-charts` in `dashboard/package.json`; do not mark it as a Vite external to work around a missing installation.
- Updated the Windows/macOS/Linux launch scripts to start both the local Python API and the Vue/Vite dashboard, so the new `App.vue` is the page users actually see. The launcher opens port `5173`; after `npm run build`, the API can serve the built dashboard from port `8765`.
