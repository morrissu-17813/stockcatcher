# AI Quant Lab War Room V8 — visual integration

## Intent
Use `assets/design/reference/tianji_3k_warroom_visual_reference.html` as a visual reference for a darker, more immersive 2.5D trading-room stage, while preserving the existing six illustrated Shih Tzu Agent sprites and the existing backend/API/ledger flow.

## Changes
- Restyled the current dashboard to a dark financial command-room palette with cyan/emerald/violet signal lighting and a perspective grid floor.
- Preserved the six existing `/agents/*-sprite.png` images; no emoji or replacement SVG characters were introduced.
- Fixed the idle-stage fallback coordinates so six Agents do not stack at the same command-center position when the backend has not assigned a `target_zone`.
- Added status-dependent signal links between CIO → Quant → Research → Risk → Execution → Auditor (and CIO → Risk). Links appear only when one of the two connected Agents has a working, warning, or success state.
- Kept role movement driven by backend `target_zone` and current status/task state. Ambient choreography remains explicitly labeled as ambience and does not create trades.
- Kept all existing market/radar/confirmation/paper-ledger controls and backend endpoints unchanged.

## Verification
- Python tests: 35 passed.
- ZIP integrity checked after packaging.
- Vue/Vite production build not run in this environment because dashboard dependencies (`node_modules`) are not installed; no claim is made that the local browser has loaded this package.

## Safety / non-goals
- Paper trading only; no live broker order path added.
- No Tianji 3K or TIDE production files modified.
- Reference HTML contains illustrative/static demo values and SVG dog drawings; it is included for reference only and is not used as the live dashboard source.
