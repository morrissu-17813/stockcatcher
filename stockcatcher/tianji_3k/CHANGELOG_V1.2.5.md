# Tianji 3K Production v1.2.5

## EARLY-MIS lightweight live-volume gate

- Keep the MIS Radar path network-free for EARLY-MIS volume estimation: no extra Fugle, FinMind, or historical API calls are made per snapshot.
- Estimate live volume pace using in-memory MIS cumulative-volume snapshots over a 45–90 second window.
- Use the already-available Stage 3 `vma5_lots` as a lightweight fallback baseline: `baseline_5m_lots = vma5_lots / 54`, then prorate by observed seconds / 300.
- EARLY-MIS requires both a live volume pace ratio >= 1.5x and at least 2 lots of observed volume in the window, in addition to existing price/breakout checks.
- Reject/rewarm the short observation window when cumulative volume rolls back, timestamps reverse, or the gap between snapshots exceeds 90 seconds.
- Include live volume pace ratio, observed window delta, window seconds, and baseline source in prediction ledger and Telegram EARLY message.
- The estimator is in-memory and resets its short observation window on process restart; it does not persist or make network requests to rebuild history.
- Preserve Fugle completed-5M evidence path for background confirmation and later signal upgrades.

## Notes

`VMA5_DAILY_DIV_54` is an inexpensive proxy, not a same-time historical baseline. The 1.5x / 45–90 second / 2-lot values are initial parameters and should be calibrated with replay data before being treated as optimal.
