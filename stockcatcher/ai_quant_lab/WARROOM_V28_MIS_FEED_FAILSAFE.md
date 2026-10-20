# V28 — MIS Feed Health and Fail-Closed Monitoring

## Why
V27 counted uncaught loop exceptions, but an MIS provider could report a failed snapshot through `last_error` without raising an exception. That meant the cycle could complete and reset the generic exception counter while the market-data feed remained unavailable.

## Changes
- Track consecutive MIS snapshot failures separately from Python cycle exceptions.
- Expose MIS failure count, threshold, and last feed error in the existing autonomy status endpoint.
- Mark monitor health `DEGRADED` while MIS feed failures are unresolved.
- Notify the Auditor role and append monitor logs for MIS failures/recovery.
- After five consecutive failed MIS snapshots, set the background stop signal (fail closed).
- Reset the MIS failure counter only after a successful snapshot. Existing exit logic still requires a fresh, traded quote and does not infer an exit from stale prices.

## Safety boundaries
- Paper-only; no broker/live-order path.
- No new tables or migration.
- No change to production Tianji 3K/TIDE or `.env`.
- This does not guarantee exchange connectivity or fill price; it makes feed failure visible and prevents indefinite autonomous operation on a broken feed.

## Validation
Run `python -m pytest -q` and `python -m compileall -q .` from this directory. Local tests do not prove live Supabase/MIS behavior.
