# Tianji 3K Production v1.2.7

## Polling observability + adaptive EARLY-MIS volume window

- Add `RADAR INTERVAL` with monotonic start-to-start interval, target interval, overrun, and previous measured cycle duration.
- Add `RADAR SCHEDULE` with mode, actual cycle duration, configured target, planned sleep, and deadline lag.
- Expand `RADAR TIMING` to expose pre-fetch work, wall-clock MIS fetch duration, state updates, Fugle scheduling, and total poll duration.
- Expand `MIS FETCH TIMING` to distinguish provider-reported duration from wall-clock duration and pre-fetch work.
- Keep EARLY-MIS volume estimation entirely in memory with no additional history/API requests.
- Expand the volume estimator's maximum tolerated observation window/gap from 90 seconds to 240 seconds. The calculation uses actual elapsed seconds, so a 120-180s observation interval is not treated as a 45-90s interval.
- Preserve strict price freshness checks and counter rollback/clock reversal/over-240s gap resets. This does not permit stale quote notifications.

## Validation

- Regression suite: **134 passed**.
- Live polling cadence still needs confirmation in the user's GitHub Actions / production environment. If `RADAR INTERVAL` remains high, use the accompanying phase timing to identify whether fetch, state processing, dynamic discovery, or scheduling dominates.
