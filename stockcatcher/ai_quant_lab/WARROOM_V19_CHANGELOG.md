# AI Quant Lab V19 — Signal Validation + Refresh Recovery

## Additive changes
- Added `signal_validation.py` for post-signal validation against completed daily OHLCV bars.
- Added `POST /api/production/validate-signal`; production signal files are read-only, no order is created, and only a Lab-owned report may be saved to `ai_quant_lab_reports` when Supabase is configured.
- Added a focused UI action for the 6278 / 2026-10-07 / 250.5 TWD case (7 trading bars, hypothetical 2% stop). Results clearly label daily-bar-only limitations and distinguish potential excursion from a next-trading-day-open scenario.
- Added an optional Gemini second-review endpoint for the completed validation report; it fails closed unless V17 persistence is healthy, stores a new evidence event, and never overwrites the original review or authorizes an order.
- Added `SupabaseStore.record_research_report` to save research validation reports without mislabeling them as daily summaries.
- Added versioned browser UI snapshot recovery in `localStorage` for view/selection and recent research outputs. This is display continuity only, never the authoritative trade ledger.
- Pauses UI polling/ambient animation work while the browser tab is hidden and refreshes on return.
- Keeps paper-only mode, existing V17/V18 persistence guards, production data read-only, and no order creation.

## Validation
- `python -m compileall -q .`: passed.
- `pytest -q`: 73 passed.
- Frontend production build could not be completed in the build container because npm dependency installation did not finish (`vite` unavailable); run `npm ci` and `npm run build` in the user's Windows environment.

## Limits
- The validation endpoint uses daily bars only; it does not claim 5-minute/tick execution fidelity or a verified strategy win.
- `MFE/MAE` are descriptive excursions over the selected observation window, not realized P&L.
- If Supabase is not configured, the report is returned to the browser but is explicitly marked not persisted.
