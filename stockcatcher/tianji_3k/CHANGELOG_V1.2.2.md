# V1.2.2

## Production fixes

- EARLY Telegram now includes `📊 預估量比` using the same one-decimal `x` format as STRONG/MOMENTUM.
- MIS no longer substitutes previous close (`y`) when last traded price (`z`) is missing/zero. Such rows are skipped for that Radar cycle, preventing fabricated previous-close snapshots from invalidating a live breakout state.
- No change to the agreed EARLY strategy gates or STRONG/MOMENTUM confirmation rules.
