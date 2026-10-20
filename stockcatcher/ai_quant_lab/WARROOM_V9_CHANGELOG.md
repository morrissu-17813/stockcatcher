# AI Quant Lab War Room V9 UI pass

## Included
- Compact top brand/status bar; removed the oversized office ceiling/banner from the office scene.
- Consolidated the six role stations into one continuous dark 2.5D-style floor, with six original sprite assets retained and only one rendered moving sprite per agent (removes duplicate overlapping dog images).
- Separated idle positions per agent; generic/default `COMMAND_CENTER` target zones no longer force every idle agent to the same point. Active role movement can use recognized backend target zones.
- Event stream uses a stable time/type/message grid, wrapping long messages without overlapping adjacent events.
- Stock rows are selectable by ticker or name. The selected market item drives quote metadata and chart data; chart toggles between intraday line and OHLC candlestick rendering using candles already returned by `/api/market`.
- Existing backend endpoints, paper-only trading boundary, six original role sprites, radar and trade confirmation flow preserved.

## Verification
- Python tests: 35 passed.
- ZIP integrity checked after packaging.
- Frontend production build could not be verified in this environment: `npm install --no-audit --no-fund` timed out before dependencies were installed. Please run `npm install` and `npm run build` locally.
- Live API connectivity cannot be tested from this environment because `127.0.0.1:8765` refers to the user's own computer. Existing API endpoints remain `/api/state`, `/api/market`, and `/api/health`.
- Chart toggles use the candle series currently returned by `/api/market` (the current provider supplies intraday 1-minute candles). This UI change does not add a separate daily-candle endpoint.
- No real broker orders are added or enabled.
