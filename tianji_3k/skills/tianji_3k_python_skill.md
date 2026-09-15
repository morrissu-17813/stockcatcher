# Tianji 3K Intraday Python Engineering Skill

**Version:** 1.0  
**Status:** ACTIVE  
**Last Updated:** 2026-09-15  
**Project:** 股市量化交易程式開發  
**Application:** 天機 3K 盤中預判引擎 V1.0

---

## 0. Purpose

This document is the engineering and strategy-development standard for the
Tianji 3K Intraday Prediction Engine.

Primary objective:

> Detect during market hours that a stock is highly likely to complete the
> daily Tianji 3K conditions by the close, without waiting until market close.

This skill combines modern Python engineering, pandas/data engineering,
API reliability, testing, Taiwan stock market data handling, Telegram
notification, structured logging, and lessons learned from the existing
V2.4 production scanner.

---

# 1. Non-Negotiable Rules

## 1.1 V2.4 Production Protection

The existing V2.4 program is a production/reference system.

**Never directly modify V2.4.**

V2.4 may be inspected, studied, imitated, refactored conceptually, and used
as a reference for validated behavior.

V2.4 must not be edited for V1.0 development or used as an experimental
runtime dependency unless explicitly approved.

The new V1.0 system is completely independent.

## 1.2 Reuse by Extraction

When V2.4 contains proven functionality:

1. Identify what has been validated.
2. Extract the underlying behavior.
3. Reimplement it cleanly in V1.0.
4. Preserve known-good behavior.
5. Improve known weaknesses.
6. Add tests around the extracted behavior.

Do not blindly copy large sections of V2.4.

## 1.3 Primary Objective

V1.0 must answer:

> Which stocks are likely to become daily 3K during today's session?

It is a low-latency intraday prediction and notification system, not an HFT
execution system.

---

# 2. V1.0 Scope

## Included

- Pre-market FULL_SCAN
- Stage 0, Stage 1, Stage 2, Stage 3
- Daily Context
- Preselected 3K pool
- Intraday whole-market discovery
- TWSE/TPEx MIS snapshot
- Intraday 3K Engine
- Breakout state machine
- Volume projection
- Market Regime
- Telegram notifications
- Structured JSONL event logs
- End-of-day Ground Truth validation
- Unit/integration tests
- API rate limiting and retry protection

## Explicitly excluded from V1.0

- LINE
- Supabase persistence
- SMC
- TIDE
- Warrant-primary analysis
- Convertible-bond analysis
- Stock-futures analysis
- Automatic order execution
- Machine-learning prediction
- Web dashboard
- Complex portfolio management

---

# 3. Architecture

Recommended structure:

```text
tianji_3k_intraday/
├── .ai/
│   └── tianji_3k_python_skill.md
├── src/
│   └── tianji_3k/
│       ├── main.py
│       ├── config.py
│       ├── models/
│       ├── data/
│       │   ├── mis.py
│       │   ├── fugle.py
│       │   └── finmind.py
│       ├── stages/
│       │   ├── stage0.py
│       │   ├── stage1.py
│       │   ├── stage2.py
│       │   └── stage3.py
│       ├── engine/
│       │   ├── daily_context.py
│       │   ├── intraday_3k.py
│       │   ├── volume_projection.py
│       │   ├── market_regime.py
│       │   └── state_machine.py
│       ├── notification/
│       │   └── telegram.py
│       └── logging/
│           └── event_logger.py
├── tests/
├── logs/
├── .env
├── .gitignore
├── pyproject.toml
└── README.md
```

Strategy code must not directly perform HTTP requests.

Notification code must not contain trading logic.

Logging code must not determine strategy state.

---

# 4. Modern Python Standard

Use modern Python practices:

- Python 3.12+ compatible code
- type hints
- dataclasses
- Enum
- pathlib
- datetime
- zoneinfo
- explicit exceptions
- small pure functions
- dependency injection where useful
- deterministic behavior
- clear naming
- minimal global state

Prefer:

```python
def evaluate_stage2(
    k0: DailyBar,
    k1: DailyBar,
    k2: DailyBar,
) -> Stage2Result:
    ...
```

over untyped, ambiguous interfaces.

Use `dataclass(slots=True)` for important runtime domain objects.

---

# 5. Type Safety

Domain logic should use typed models.

Example:

```python
@dataclass(slots=True)
class StockSnapshot:
    symbol: str
    price: float
    prev_close: float
    volume_lots: int
    up_pct: float
    timestamp: datetime
```

Example:

```python
@dataclass(slots=True)
class DailyContext:
    symbol: str
    k1_high: float
    k2_high: float
    breakout_level: float
    ma20: float
    ma60: float
    vma5_lots: float
    yesterday_volume_lots: int
```

Dictionaries are acceptable at API and serialization boundaries, but avoid
deep nested dictionaries throughout strategy logic.

---

# 6. Time and Timezone

Use:

```python
from zoneinfo import ZoneInfo

TAIPEI_TZ = ZoneInfo("Asia/Taipei")
```

All application timestamps must be timezone-aware.

Trading schedule:

```text
08:20  FULL_SCAN
09:00  Market Open
13:30  Market Close
13:35  Finalization / shutdown
```

Never mix naive and timezone-aware datetimes.

---

# 7. Historical Data

Primary source: Fugle Historical Candles.

Fallback: FinMind.

Do not redundantly request the same stock from both providers.

Preferred:

- `adjusted=false`
- initially about 100 calendar days
- require at least 65 valid trading days
- expand to about 180 days if necessary
- calculate SMA locally

Never blindly use the final row as the latest completed day. Explicitly
exclude today's incomplete date when determining the latest completed session.

---

# 8. Volume Units

Historical volume is in shares.

Standardize internally:

```text
volume_shares
volume_lots
```

Conversion:

```python
volume_lots = volume_shares / 1000
```

All Stage 3 thresholds use lots.

Never mix shares and lots inside strategy calculations.

---

# 9. Stage 0 — Liquidity / Universe

Keep only:

- TWSE listed ordinary common stocks
- TPEx OTC ordinary common stocks

Exclude:

- Emerging stocks
- ETFs
- ETNs
- warrants
- preferred shares
- bonds
- DRs
- disposal stocks
- suspended stocks
- abnormal/non-normal trading
- malformed symbols/data

Optional coarse liquidity rule:

```text
Yesterday volume < 500 lots → exclude
```

Do not spend roughly 1,800 extra API calls solely to obtain this value if it
is not cheaply available.

Preferred exclusion order:

```text
Product type
→ Market
→ Disposal/suspension/status
→ Data quality
→ Yesterday volume
```

---

# 10. Stage 1 — Trend

Hard conditions:

```text
Close > MA20
Close > MA60
MA20 > MA60
MA20(today) > MA20(previous day)
```

Auxiliary:

- MA20 slope %
- Close vs MA20 %
- Close vs MA60 %
- trading_days

Calculate SMA locally from historical candles.

---

# 11. Stage 2 — Breakout

Definitions:

```text
K0 = latest completed trading day
K1 = previous trading day
K2 = two trading days before K0
```

Hard conditions:

```text
K0 Close > K0 Open
K0 gain >= 4%
K0 High > K1 High
K0 High > K2 High
K0 Close > max(K1 High, K2 High)
```

```text
breakout_level = max(K1 High, K2 High)
```

A limit-up stock is not automatically a valid 3K breakout.

---

# 12. Stage 3 — Volume

Hard conditions:

```text
5-day average volume >= 1,000 lots
Today volume > Yesterday volume
Today volume / 5-day average volume >= 1.5x
```

During market hours, final today's volume is unknown, so use projected EOD
volume for intraday prediction.

---

# 13. Daily Context

Pre-market FULL_SCAN produces one lightweight DailyContext per candidate.

It should contain the immutable session reference values required by the
intraday engine:

- previous close
- K1 high
- K2 high
- breakout level
- MA20
- MA60
- VMA5
- yesterday volume
- relevant Stage 0–3 reference flags

Keep this in RAM for the session.

Do not repeatedly fetch historical data during market hours.

---

# 14. Intraday Data Layer

Primary broad-market source:

**Existing validated TWSE/TPEx MIS batch snapshot approach from V2.4.**

The proven concept extracts:

- symbol
- current price
- previous close
- cumulative volume
- percentage change
- trading status
- bid/ask information when available

V1.0 should reimplement this independently while preserving the validated
behavior.

One MIS snapshot should feed:

```text
Price Monitoring
3K Engine
Preselected Pool
Intraday Discovery
Market Breadth
Market Regime
```

Do not create a second whole-market intraday API loop for 3K.

---

# 15. MIS Polling

V1.0 requirement:

```text
Every 20 seconds during market hours
```

The scheduler must tolerate:

- network latency
- request failure
- retry delay
- clock drift
- slow responses

Do not unintentionally overlap multiple whole-market scans.

A duplicate/replayed snapshot must not count as a new confirmation.

---

# 16. Intraday 3K Engine

The engine predicts whether today's final daily 3K conditions are becoming
likely.

Input:

```text
DailyContext
+
current MIS snapshot
+
market context
```

The engine must not own:

- HTTP
- Telegram
- Supabase
- scheduling
- persistence

It should implement:

```text
Input → Calculation → Structured Result
```

---

# 17. Intraday Price Conditions

Monitor:

```text
current_price > K1 High
current_price > K2 High
current_price / previous_close - 1 >= 4%
current_price > today's open
```

Primary reference:

```text
breakout_level = max(K1 High, K2 High)
```

---

# 18. Effective Breakout

Locked V1.0 rule:

```text
breakout amplitude >= 0.3%
+
two consecutive valid snapshots
```

Formula:

```python
current_price >= breakout_level * 1.003
```

A confirmation requires a genuinely new market-data observation.

Do not count the same API response twice.

---

# 19. Volume Projection

Initial model:

```text
estimated_eod_volume =
    current_cumulative_volume * 270 / elapsed_minutes
```

Calculate:

```text
estimated_vs_yesterday =
    estimated_eod_volume / yesterday_volume
```

and:

```text
estimated_vs_vma5 =
    estimated_eod_volume / vma5
```

This is intentionally a V1.0 baseline.

Future versions may replace it with a time-of-day volume curve after sufficient
real-session data is collected.

---

# 20. Early-Session Protection

From 09:00–09:05:

- price breakout can be detected
- ordinary state transitions can occur
- linear volume projection is considered unstable
- early volume alone must not create maximum-confidence status

---

# 21. Intraday State Machine

Required states:

```text
WATCH
APPROACHING
BREAKOUT
PRE_3K
HIGH_CONFIDENCE
BREAKOUT_LOST
SECOND_BREAKOUT
CLOSED
```

Normal progression:

```text
WATCH
→ APPROACHING
→ BREAKOUT
→ PRE_3K
→ HIGH_CONFIDENCE
```

Failure:

```text
BREAKOUT/PRE_3K
→ BREAKOUT_LOST
```

Recovery:

```text
BREAKOUT_LOST
→ SECOND_BREAKOUT
```

End of day:

```text
CLOSED
```

---

# 22. Telegram

V1.0 uses Telegram only.

No LINE.

Telegram is a notification layer, not the strategy engine.

Main event priorities:

```text
P1 HIGH_CONFIDENCE
P2 PRE_3K
P3 BREAKOUT
P4 SECOND_BREAKOUT
```

Approaching-breakout is normally an internal state and does not need a Telegram
message.

---

# 23. Telegram Daily Limit

Recommended hard ceiling:

```text
50 major notifications per trading day
```

This is a safety ceiling, not a target.

Priority when the ceiling is approached:

```text
P1 > P2 > P3 > P4
```

Normal operation should aim for meaningful alerts rather than high volume.

---

# 24. Notification Deduplication

Use:

```text
State Machine
+
Event ID
+
Valid Snapshot Identity
+
Cooldown / Oscillation Protection
```

Do not rely solely on a time-based cooldown.

Rules:

- first effective breakout → notify once
- PRE_3K transition → notify once
- HIGH_CONFIDENCE transition → notify once
- continued same state → suppress
- tiny move below breakout → do not immediately fail
- confirmed failure → BREAKOUT_LOST
- confirmed new breakout after failure → SECOND_BREAKOUT may notify
- repeated oscillation → suppress unless breakout quality materially improves

Suggested maximum major notifications per stock per day:

```text
First Breakout
PRE_3K
Second Breakout / major re-acceleration
```

The global daily cap remains 50.

---

# 25. Breakout Failure

Initial failure rule:

```text
price < breakout_level * 0.997
+
two valid snapshots
```

This is a configurable testing parameter.

A single tick below the breakout level is not automatically a failed breakout.

---

# 26. Intraday Score

Use a condition-completion score, not an assumed probability.

Example:

```text
Break K1/K2                    +25
Gain >= 4%                     +15
Effective breakout >= 0.3%     +10
Projected volume >= 1.5x VMA5  +15
Projected volume >= yesterday  +15
Projected volume >= 1.8x VMA5  +10
Breakout persistence           +10
```

State mapping:

```text
0–39    WATCH
40–59   APPROACHING
60–74   BREAKOUT
75–89   PRE_3K
90–100  HIGH_CONFIDENCE
```

Do not call score 90 "90% probability" until empirical calibration exists.

---

# 27. Market Regime

Market Regime is auxiliary and must never block a strong individual-stock
signal.

States:

```text
RISK_ON
NEUTRAL
RISK_OFF
```

Use the same broad MIS data for market breadth where practical:

```text
advance_count
decline_count
flat_count
```

Calculate:

```text
ADR = advances / max(declines, 1)

breadth =
    (advances - declines) / valid_stock_count
```

Index direction should use existing verified market-data infrastructure when
available. If an additional index request is needed, keep it low-frequency and
separate from the 20-second stock scan.

Do not introduce an expensive redundant market-data feed solely for V1.0.

---

# 28. Market Regime Interpretation

Baseline interpretation:

```text
RISK_ON
    positive index direction
    + clearly positive breadth

NEUTRAL
    mixed/range-bound conditions

RISK_OFF
    negative index direction
    + clearly negative breadth
```

Exact numerical thresholds must remain configurable.

A strong individual stock may still generate PRE_3K in RISK_OFF.

The Telegram message should make the regime visible, e.g.:

```text
市場環境：RISK_OFF
個股：逆勢突破
```

---

# 29. Preselected vs Intraday Discovery

Two entry paths:

## PRESELECTED

Passed the pre-market 3K selection.

```text
source = PRESELECTED
```

## INTRADAY_DISCOVERY

Was not in the pre-market pool but develops a strong intraday structure.

```text
source = INTRADAY_DISCOVERY
```

Telegram must distinguish these sources.

---

# 30. Event Logging

Write:

```text
logs/YYYY-MM-DD_events.jsonl
```

One JSON object per line.

Every meaningful event should include, where available:

```text
event_id
date
time
symbol
name
source
state
previous_state
price
today_open
previous_close
up_pct
k1_high
k2_high
breakout_level
breakout_pct
current_volume_lots
yesterday_volume_lots
vma5_lots
estimated_eod_volume_lots
estimated_vs_yesterday
estimated_vs_vma5
stage1_pass
stage2_pass
stage3_projected_pass
breakout_hold_count
score
market_regime
notification_sent
```

The log must be sufficient to explain why a notification was generated.

---

# 31. Event vs Snapshot Logs

Event logs:

- BREAKOUT
- PRE_3K
- HIGH_CONFIDENCE
- BREAKOUT_LOST when relevant
- SECOND_BREAKOUT
- final validation

Snapshot logs may be limited to:

- preselected candidates
- active candidates
- approaching-breakout stocks

Do not create unnecessary permanent full-market snapshot logs.

---

# 32. Ground Truth

After 13:30, retrieve the completed daily candle and determine the true final:

```text
Stage 0
Stage 1
Stage 2
Stage 3
3K PASS / FAIL
```

Preferred source:

```text
Fugle Historical
```

This final result is the Ground Truth.

Never alter the original intraday event with future information.

---

# 33. Post-Signal Tracking

For meaningful events, record where practical:

```text
+5 minutes
+15 minutes
+30 minutes
+60 minutes
close
```

And:

```text
max_price_after_signal
max_gain_pct
close_price
close_gain_pct
final_3k_pass
```

This allows analysis of both 3K success and post-signal trading opportunity.

---

# 34. Empirical Validation

Never invent the system's success rate.

Eventually calculate:

```text
BREAKOUT → 3K success rate
BREAKOUT + VOLUME → 3K success rate
PRE_3K → 3K success rate
HIGH_CONFIDENCE → 3K success rate
```

Segment by:

```text
time of day
market regime
breakout magnitude
volume ratio
industry
preselected vs discovery
first vs second breakout
```

Only after sufficient observations should thresholds be statistically calibrated.

---

# 35. No Look-Ahead Bias

At time T, the strategy may use only information available at or before T.

Never use:

- future price
- future volume
- future candle close
- future market regime
- final daily volume

to generate a historical intraday signal.

Ground Truth is only for post-event validation.

---

# 36. API Engineering

Every API client must provide:

- timeout
- limited retry
- backoff where appropriate
- rate limiting
- response validation
- structured error reporting
- graceful failure

Suggested behavior:

```text
429          → backoff/retry
500/502/503  → limited retry
timeout      → limited retry
400          → normally no retry
401/403      → fail fast
```

Never retry forever.

Never silently ignore API errors.

---

# 37. Rate-Limit Protection

Treat free API limits as hard constraints.

Never use uncontrolled request blasts.

Fugle:

- minimize historical requests
- one historical request per stock where possible
- calculate indicators locally

FinMind:

- fallback only
- avoid redundant duplicate calls

MIS:

- use the validated batch strategy
- one broad snapshot serves multiple engines

---

# 38. Async Standard

Do not introduce async merely because it is modern.

Use synchronous code where it is clearer and sufficient.

Use asyncio only when concurrent I/O genuinely helps.

If async is introduced:

- prefer structured concurrency
- use timeouts
- handle cancellation correctly
- prevent orphan tasks
- bound concurrency

Strategy logic must remain independent of sync/async implementation.

---

# 39. pandas Standard

Use pandas primarily for:

- historical OHLCV
- batch transformations
- indicator calculations
- analytical datasets
- post-session analysis

Do not use one giant DataFrame as the entire runtime state machine.

Use typed objects for runtime domain state.

Avoid chained assignment and ambiguous mutation.

---

# 40. Testing Standard

Use pytest from the beginning.

Minimum tests:

## Stage 0

- ETF exclusion
- warrant exclusion
- preferred stock exclusion
- disposal exclusion
- suspension exclusion
- invalid symbol
- liquidity threshold

## Stage 1

- Close > MA20
- Close > MA60
- MA20 > MA60
- MA20 slope
- exact boundary failures

## Stage 2

- bullish K
- 3.99%, 4.00%, 4.01%
- high equal to K1
- high above K1
- high above K2
- close below breakout
- close above breakout

## Stage 3

- VMA5 below 1000
- exactly 1000
- ratio 1.49x, 1.50x, 1.51x
- volume below/above yesterday

## Intraday

- approach
- first breakout
- duplicate snapshot
- second confirmation
- false breakout
- PRE_3K
- HIGH_CONFIDENCE
- breakout loss
- second breakout
- close

---

# 41. Boundary Testing

Every numerical threshold requires tests around:

```text
threshold - epsilon
threshold
threshold + epsilon
```

Examples:

```text
3.99% / 4.00% / 4.01%
0.29% / 0.30% / 0.31%
1.49x / 1.50x / 1.51x
```

---

# 42. Ruff / Formatting

Use Ruff:

```text
ruff check
ruff format
```

Use a consistent project configuration in `pyproject.toml`.

Do not add many overlapping formatters or linters without a clear reason.

---

# 43. Configuration

Do not scatter magic numbers.

Centralize strategy parameters.

Example:

```python
class Config:
    FULL_SCAN_TIME = "08:20"
    MIS_INTERVAL_SECONDS = 20
    MIN_GAIN_PCT = 4.0
    MIN_BREAKOUT_PCT = 0.3
    BREAKOUT_CONFIRMATIONS = 2
    MIN_VMA5_LOTS = 1000
    MIN_VOLUME_RATIO = 1.5
    HIGH_VOLUME_RATIO = 1.8
    MAX_DAILY_TELEGRAM_ALERTS = 50
```

Credentials belong in environment variables, never source code.

---

# 44. Error Handling

Never silently swallow exceptions.

A malformed stock should not terminate the whole scan.

Differentiate:

```text
individual stock data failure
API/provider failure
strategy failure
application failure
```

Use structured logging for each class.

---

# 45. Graceful Shutdown

Handle:

- Ctrl+C
- scheduler shutdown
- network failure
- API failure
- Telegram failure
- market close

At close:

```text
stop new market scans
finalize events
perform Ground Truth validation
write final logs
shutdown cleanly
```

---

# 46. Telegram Failure Isolation

If Telegram fails:

```text
Strategy continues
Logging continues
Notification failure is recorded
```

Telegram failure must never terminate the scanner.

---

# 47. Security

Never put credentials in:

- source code
- Git
- logs
- Telegram messages
- documentation
- screenshots

If a credential has been exposed, treat it as compromised and rotate it.

Do not copy V2.4 credentials into V1.0.

---

# 48. Observability

The application should report:

```text
scan start/end
stock counts
Stage 0/1/2/3 counts
preselected count
intraday discovery count
MIS latency
API failures
Telegram failures
events generated
events suppressed
```

The system must be able to explain what it did.

---

# 49. Performance

Optimize network/API behavior before CPU arithmetic.

Priority:

```text
1. Avoid unnecessary network requests
2. Batch data
3. Cache immutable session context
4. Keep strategy calculations in RAM
5. Avoid redundant pandas work
6. Profile before micro-optimizing
```

---

# 50. Development Workflow

For each feature:

```text
1. Define requirement
2. Define data contract
3. Define edge cases
4. Write/adjust tests
5. Implement
6. Run Ruff
7. Run pytest
8. Observe live/paper behavior
9. Inspect logs
10. Review results
```

Do not change multiple major subsystems at once.

---

# 51. V2.4 Lessons Learned / Known Traps

Treat these as permanent guardrails:

- API overload
- free API rate limits
- today's incomplete candle mistaken for completed data
- shares/lots confusion
- unreliable early-session linear volume projection
- duplicate snapshot counting
- false breakout from a single tick
- limit-up incorrectly treated as automatic 3K
- confusion between rolling 3×5-minute breakout and daily 3K
- monolithic architecture
- notification spam
- secrets in source code
- redundant provider requests

---

# 52. Canonical Daily 3K Definition

Stage 0 must pass.

Stage 1:

```text
Close > MA20
Close > MA60
MA20 > MA60
MA20 slope up
```

Stage 2:

```text
Bullish K
Gain >= 4%
High > K1 High
High > K2 High
Close > breakout level
```

Stage 3:

```text
5-day average volume >= 1000 lots
Today volume > yesterday volume
Today volume / 5-day average volume >= 1.5x
```

Complete pipeline:

```text
Stage 0
→ Stage 1
→ Stage 2
→ Stage 3
→ 3K PASS
```

---

# 53. Intraday Prediction Definition

The Intraday Engine estimates whether today's final daily 3K conditions are
becoming likely.

Terminology:

```text
BREAKOUT
    Price structure has broken the defined level.

PRE_3K
    Price, gain, projected volume, trend, and breakout conditions indicate
    high likelihood of final 3K completion.

HIGH_CONFIDENCE
    Stronger PRE_3K state with stronger breakout persistence and volume.

CONFIRMED
    Final daily data confirms the completed 3K.
```

Do not call an intraday prediction "confirmed."

---

# 54. Development Priority

If scope grows too large, prioritize:

```text
1. Correct data
2. Correct Stage 0–3
3. Correct Daily Context
4. Correct Intraday Breakout
5. Correct Volume Projection
6. Correct State Machine
7. Correct Deduplication
8. Telegram
9. Structured Logs
10. Ground Truth
11. Market Regime
12. Performance optimization
```

Accuracy and observability come before feature count.

---

# 55. Final Engineering Principle

> **V2.4 supplies validated field experience. V1.0 supplies clean engineering.**

Use:

```text
Validated V2.4 behavior
→ Extract
→ Simplify
→ Type
→ Test
→ Integrate
```

Do not recreate every V2.4 feature.

The objective is not to build the biggest scanner.

The objective is to build the most reliable system for answering:

> **Which stock is most likely to become today's 3K, right now?**

---

# 56. Future Evolution

After enough real-session logs exist, future versions may introduce:

- time-of-day volume curves
- statistical probability calibration
- score calibration
- market-regime conditioning
- breakout-quality models
- industry-relative strength
- SMC integration
- TIDE integration
- warrant/CB/futures capital-flow modules
- machine-learning models
- advanced backtesting

Only add these after V1.0 produces clean, auditable observations.

---

# 57. Versioning

```text
1.0  Initial engineering standard
1.1  Minor clarification
1.2  Testing/architecture improvement
2.0  Major strategy or architecture change
```

When a strategy rule changes, update this file and the relevant tests.

Never silently change a locked rule.

---

# 58. Agent Instruction

Any coding agent using this skill must:

1. Read this document before modifying Tianji 3K V1.0.
2. Treat Non-Negotiable rules as mandatory.
3. Never modify V2.4 production code.
4. Prefer small, testable modules.
5. Preserve data units and timestamps.
6. Prevent look-ahead bias.
7. Protect API limits.
8. Keep Telegram separate from strategy logic.
9. Log meaningful events.
10. Preserve enough evidence for quantitative review.
11. Ask for clarification when a request conflicts with this document.
12. When a rule intentionally changes, update the implementation, tests, and
    specification together.

---

**END OF TIANJI 3K INTRADAY PYTHON ENGINEERING SKILL v1.0**
