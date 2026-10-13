# Tianji 3K Production v1.2.6

## Root-cause fix: slow MIS Radar and late limit-up alerts

- Increase the default MIS query batch size from 25 to 100 symbols, reducing the number of sequentially requested market-data batches.
- Fetch multiple MIS batches concurrently with a bounded 4-worker pool and persistent per-worker sessions; a failed batch no longer discards successful batches.
- Add `MIS FETCH TIMING` telemetry (elapsed time, batch count, workers, requested/returned symbols, failed batches).
- Include the complete MIS network-fetch duration in `RADAR TIMING`; prior logs only measured the post-fetch processing phase and hid the dominant latency.
- Parse the exchange last-trade date/time (`d` + `t`) separately from local HTTP receive time. Preserve receive time for low-cost live-volume deltas, but use exchange quote age to validate signal freshness.
- Suppress candidate processing and notifications when the MIS last-trade time is unknown or older than 60 seconds. This prevents a newly received HTTP payload containing an old limit-up quote from being treated as a fresh signal.
- Add a 300-second trigger TTL. After a trigger has remained pending for 5 minutes without confirmation, stop retrying Fugle for that old event and suppress late EARLY/STRONG/MOMENTUM messages. A later invalidation and new trigger can start a new window.
- Keep EARLY-MIS volume estimation memory-only: no extra per-snapshot Fugle/FinMind/history API calls.
- Add tests for exchange quote-time parsing, concurrent MIS batch aggregation, stale quote suppression, and trigger TTL.

## Configuration defaults

- `TIANJI_MIS_BATCH_SIZE=100`
- `TIANJI_MIS_FETCH_WORKERS=4`
- `TIANJI_MIS_MAX_QUOTE_AGE_SECONDS=60`
- `TIANJI_FUGLE_PENDING_TTL_SECONDS=300`

These defaults are intentionally conservative and should be reviewed against live `MIS FETCH TIMING` logs. The 60-second quote-age limit and 300-second trigger TTL prevent stale notifications but may suppress late confirmations by design.
