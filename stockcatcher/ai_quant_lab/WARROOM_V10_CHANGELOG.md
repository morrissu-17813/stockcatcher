# AI Quant Lab V10 — Cozy Shared Office

## UI changes
- Reduced visible Agent sprite size to approximately 38–50 px on desktop (responsive down to 38 px on mobile) so characters feel like small office companions at their desks.
- Replaced the six large dashboard-like station cards with compact desk islands: warm oak surfaces, monitor, keyboard/device detail, mug, desk legs, and small nameplates.
- Reworked the shared floor into a warmer office palette with wood flooring and soft room lighting.
- Added decorative kitchenette / coffee corner, lounge nook, and two plants.
- Restyled central meeting table with warm wood and rounded furniture-like shape.
- Kept the original six sprite PNGs, existing API endpoints, state handling, stock chart, event stream, and paper-trading logic unchanged.

## Verification
- `python -m pytest -q`: 35 passed.
- ZIP integrity verified after packaging.
- Vue/Vite production build not run in this environment because dashboard npm dependencies are not installed here. Please run `npm run build` locally before replacing the active test version.
