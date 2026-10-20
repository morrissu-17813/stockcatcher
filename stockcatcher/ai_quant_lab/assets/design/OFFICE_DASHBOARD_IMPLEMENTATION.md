# AI Quant Lab Office Dashboard — Implementation Note

## Scope
- Isolated under `stockcatcher/ai_quant_lab/` only.
- The office-floor layout is rendered by `preview.html`; the API and paper ledger remain the source of truth.
- Six roles retain consistent card/avatar dimensions, with warm office desks, window backdrop, floor labels, role/status labels, and task panels.
- Office choreography cycles through sit, think, stand, walk-to-brief, report, return, and sit. This is presentation-only and must never create a market event, order, fill, or profit.
- Actual task states from `/api/state` override office choreography for working, warning, and completed states.
- Paper-only boundary remains unchanged; no broker or live order connection.

## Current limitation
Current role assets are static character portraits. CSS choreography animates the full portrait and provides spatial cues; it does not yet rig individual limbs or use frame-by-frame walk/sit sprite sequences. For true articulated movement, replace each role portrait with transparent pose assets or a sprite sheet and keep the same `/api/state` status adapter.

## Validation
Run `python -m unittest discover -s tests -q`. The office animation state is client-side presentation; market data, event stream, and paper ledger continue to come from the local Python API.
