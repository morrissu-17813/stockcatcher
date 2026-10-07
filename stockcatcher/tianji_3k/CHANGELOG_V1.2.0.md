# Tianji 3K Production v1.2.0

## Intraday notification tuning
- Keep the existing hard price/state gates.
- Fugle 5M micro volume threshold lowered from 1.20x to 1.05x for discovery.
- Projected volume >= 1.50x remains STRONG.
- Projected volume 1.30x-<1.50x can now produce EARLY.
- Below 1.30x remains audit-only/retry.
- >= 9.5% is no longer suppressed; labeled MOMENTUM.
- Telegram labels EARLY / STRONG / MOMENTUM.
- Premarket Stage 0-3 rules are unchanged.
