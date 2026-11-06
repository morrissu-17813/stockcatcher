# Technical Indicator Engine: Current Design and Development Notes

Status date: 2026-11-01

This is the current design record for `stockcatcher/technical_indicator_engine.py`. It supersedes strategy thresholds and Tier descriptions in older quick-start notes, especially the previous claim that a 2.5x same-time volume ratio is a required Tier 1 condition.

## 1. Purpose and Scope

The engine monitors a rolling pool of Taiwan stocks associated with actively traded warrants. It looks for a short-term volume/price surge in MIS, confirms a completed five-minute 3K breakout through Fugle, applies daily-trend and score checks, then sends a Telegram message. The current live path is an alert/radar, not a fully modeled order execution or backtest engine.

The main live path is:

```text
Warrant underlying pool
  -> MIS rolling volume/price surge
  -> Fugle completed 5-minute candles
  -> effective 3K + live price above 5-minute MA20
  -> completed-daily snapshot and daily gate
  -> same-time volume flag + intraday confirmation score
  -> FinMind insider / Supabase TDCC enrichment for candidates
  -> tier classification and Telegram
```

A successful startup Telegram message confirms delivery configuration, not that any trading signal passed.

## 2. Pool and MIS Candidate Gate

- The default warrant underlying quota is 50 stocks.
- `run_cycle()` checks at most the first 20 MIS hits for Fugle 3K confirmation.
- The MIS scanner groups stocks and queries them in parallel, up to three groups at once.
- Per-symbol rolling history uses approximately 60 seconds, and a baseline older than 75 seconds is discarded and warmed up again.
- An MIS hit requires a positive volume increase, estimated turnover of at least NT$2 million, and price no lower than the baseline price.
- The live loop targets a 10-second start cadence and refreshes the pool every five minutes.

These are candidate filters, not a guarantee of a buy or fill.

## 3. Effective Five-Minute 3K

`detect_effective_3k_breakout()` operates only on completed candles and treats the final three completed bars as K1, K2, K3.

Price condition:

```text
K3 close > max(K1 high, K2 high)
```

Volume baseline:

- The five bars immediately before K3 are used. They include K1 and K2 and exclude K3.
- The minimum volume multiplier is 1.2x. Opening and regular-session multipliers are both currently 1.2x.
- K3 volume equal to the threshold passes; below it fails.

Moving averages and stop reference:

- The 5-minute MA5 is calculated from the five closes immediately before K3.
- The 5-minute MA20 is calculated from the 20 closes immediately before K3.
- These windows include K1/K2 and exclude K3.
- The stop reference returned by the detector is the minimum low among K1, K2, K3; the current alert path does not execute this as an order stop.

At least 21 completed bars are required to have 20 bars before K3. In `run_cycle()`, the MIS current price must also be strictly above the returned 5-minute MA20.

## 4. Daily Features and Score

Historical daily candles are loaded on demand into the engine cache. `_safe_snapshot()` removes the current day's not-yet-completed daily candle before computing the daily snapshot. It then keeps the daily values separate from the live MIS quote:

- `daily_close`, `daily_score`, `daily_is_3k_breakout`, `daily_is_5k_breakout`: completed daily-bar values.
- `close`, `volume`: current MIS quote/volume used for live context.
- `score` remains a compatibility alias for `daily_score`.

The existing daily technical score is additive and clipped to 0-100:

| Daily condition | Score change |
| --- | ---: |
| Daily close > MA20 | +25 |
| Daily close > MA5 | +15 |
| RSI14 >= 50 | +15 |
| RSI14 >= 70 | -10 |
| Daily 3-bar breakout | +30 |
| Daily 5-bar breakout | +20 |
| Daily volume / VOL_MA20 > 1.5 | +15 |
| MACD histogram > 0 | +10 |

Tier 1 requires `daily_score >= 60` and the daily bullish condition below. The score is a hand-built heuristic, not a calibrated probability or validated estimate of win rate.

Daily bullish condition:

```text
(daily_close > MA5 > MA20)
OR daily_is_3k_breakout
OR daily_is_5k_breakout
OR (RSI14 > 50 AND MACD histogram > 0)
```

The live 5-minute 3K signal is now stored as `effective_3k_confirmed`; it must not overwrite the daily breakout flags. This prevents a live 3K from making the daily bullish OR condition automatically true.

## 5. Intraday Confirmation Score

The engine also reports a separate descriptive `intraday_score`, from 0 to 100. It is not currently an alert gate:

| Intraday evidence | Score |
| --- | ---: |
| Effective 3K confirmed | +30 |
| MIS current price > 5-minute MA20 | +25 |
| MIS current price >= K3 close | +15 |
| K3 volume ratio >= 1.5x | +15 |
| Optional same-time volume flag passes | +15 |

The K3 hard volume gate remains 1.2x. The separate 1.5x score component is a stronger-volume label, not a second hard gate. Both daily and intraday scores are printed in Telegram messages so they can be evaluated independently before deciding whether to gate on the intraday score.

## 6. Five-Day Same-Time Volume Flag

`_get_same_time_volume_baseline()` compares today's completed-bar cumulative volume with the median cumulative volume at the same clock time over the most recent five historical trading dates:

```text
same_time_ratio = today's completed 5-minute cumulative volume
                   / median(previous 5 trading dates at same cutoff)
```

The cutoff is floored to the most recent completed five-minute boundary. The threshold is 1.5x. The result is informational only:

- `same_time_volume_flag=True` when a valid ratio is >= 1.5x.
- `False` when a valid ratio is below 1.5x.
- `same_time_volume_available=False` when history is unavailable/insufficient; the notification may still proceed.

The diagnostic log reports `passed`, `below_threshold`, and `unavailable` separately. It must not count these states as rejected alerts.

## 7. Tier Logic and Data Sources

### Tier 1

Requires the effective 3K to exist, current MIS price above 5-minute MA20, daily score >= 60, and daily bullish condition. Same-time volume is not required.

### Tier 2

Tier 1 plus positive insider net buy from FinMind `TaiwanStockInsiderTrading` over the existing 30-calendar-day lookup. The live cycle loads the whole-market insider mapping only for 3K/MA20 candidates and caches it for one hour.

### Tier 3

Tier 2 plus both:

- Existing FinMind `buy_streak >= 3` condition.
- A fresh Supabase TDCC `ratio_400k` increase versus the prior report.

`ratio_400k` is the percentage of custodial shares held by accounts in the >=400-lot bands. It is **not** a count of lots bought. The engine computes:

```text
big_holder_change_400k_pp = latest ratio_400k - previous report ratio_400k
```

Tier 3 requires the change to be positive. The latest report must be no more than 14 calendar days old and two valid report rows must exist. `ratio_1000k` and its change are also retrieved for diagnostics/future research, but are not part of the current Tier 3 gate. Supabase reads use `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` from environment variables, batch candidate symbols, and cache valid results for six hours (unavailable results for five minutes).

Tier 3 Telegram reason and alert metadata identify the TDCC source and show the percentage-point change. If TDCC is missing or stale, Tier 1/2 can still notify; only Tier 3 is unavailable.

### Tier 3 caveat

The current insider `buy_streak` is derived from consecutive calendar dates in the FinMind result. Weekends/holidays and the dataset's event/reporting semantics may make this condition overly restrictive or semantically different from “three consecutive trading sessions.” It remains unchanged for now and needs a separate data-definition decision before loosening it.

The older `_fetch_real_chip_signal()` helper also reads institutional and margin data, but the live `run_cycle()` Tier path currently uses FinMind insider data and TDCC data; it does not fetch foreign/investment/dealer/margin datasets for each alert.

## 8. Duplicate and Cooldown Behavior

- A signal key is based on `symbol` plus the completed K3 bar timestamp.
- Successfully sent signal keys are retained in `sent_signals` for this process lifetime.
- A per-symbol 30-minute cooldown is applied after successful Telegram delivery.
- A failed Telegram send is logged and does not mark the signal as sent.

## 9. Diagnostics and Tests

Each scan logs MIS/Fugle timings, hit counts, API failures, rejection counts, optional volume-flag counts, alert count, and total elapsed time. TDCC/insider data are not logged with secrets.

Offline verification currently covers:

- Intraday effective 3K does not substitute for daily bullish structure.
- Daily and intraday scores are separate.
- In-progress same-day daily candles are excluded from daily snapshots.
- Same-time volume below threshold or unavailable does not block Tier 1.
- TDCC report parsing, freshness, ratio differences, and Tier 3 positive/negative cases.
- `run_cycle()` passes mocked insider/TDCC data through to Tier 3 and the Telegram message.

Run the focused tests:

```powershell
python -X utf8 -m pytest test_technical_indicator_engine.py -q
python -X utf8 test_priority_logic.py
```

The live Supabase query has not been verified against production in this development session; the TDCC integration tests use mocked responses. The full integration script makes external API calls and should be run deliberately, not as an offline unit test.

## 10. Recommended Next Improvements

Prioritize these in order; do not add several indicators and tune all thresholds on the same history.

1. **Validate insider streak semantics.** Confirm whether FinMind rows represent daily trading activity or dated disclosure events. If not, replace “three consecutive days” with a documented, testable event-window rule or a trading-calendar-aware rule.
2. **Log score components and TDCC evidence per candidate.** Record daily score components, intraday score components, TDCC report dates, `ratio_400k` current/prior/delta, insider source date, and exact gate result. This will reveal which signals are being filtered without logging credentials.
3. **Backtest event timing correctly.** The 3K is only known after K3 closes. Simulate entry at the next executable price (not the same close), include Taiwan commissions/tax, spread and slippage, and test liquidity/volume impact.
4. **Use walk-forward and a truly out-of-sample period.** Freeze thresholds before evaluating the held-out period. Compare the base strategy against one change at a time: daily trend gate, K3 volume ratio, same-time flag, TDCC change, and intraday score.
5. **Evaluate more than win rate.** Track expectancy, average win/loss, profit factor, drawdown, trade count, performance by market regime, and net results after costs. High win rate alone can hide a few very large losses.
6. **Only promote a score/flag to a gate if it adds out-of-sample value.** The intraday score and same-time volume flag are currently descriptive. Their weights/thresholds have not been calibrated on held-out data.
7. **Consider asynchronous or bounded chip-data refresh.** FinMind and Supabase run only for candidates and are cached, but a first refresh can add latency. If logs show material delay, refresh in the background with bounded timeouts and keep the last known fresh value with an explicit stale flag.
8. **Security: rotate exposed service-role credentials.** The reference `concept_stock_mapper.py` attachment contains a hard-coded Supabase service-role key. Rotate it in Supabase, remove hard-coded copies from tracked scripts, and keep the replacement only in local ignored `.env` / GitHub Actions Secrets. Do not copy secret values into this document or logs.

## 11. Source References

- [AQR: Time Series Momentum](https://www.aqr.com/Insights/Research/Journal-Article/Time-Series-Momentum): evidence for time-series momentum in 58 futures/forward markets; the paper's horizons are much longer than this intraday Taiwan strategy, so it motivates a hypothesis rather than validates this trigger.
- [AQR: A Century of Evidence on Trend-Following Investing](https://www.aqr.com/Insights/Research/Journal-Article/A-Century-of-Evidence-on-Trend-Following-Investing): long historical context for trend following; not a 5-minute-stock win-rate claim.
- [AQR: Momentum Crashes](https://www.aqr.com/Insights/Research/Journal-Article/Momentum-Crashes): illustrates that momentum returns can have severe conditional crash periods.
- [Lee and Swaminathan: Price Momentum and Trading Volume](https://doi.org/10.1111/0022-1082.00280): reports that past trading volume predicts momentum magnitude/persistence and eventual reversal in its studied equity sample; it does not determine the correct 1.5x threshold for this engine.
- [QuantConnect: Research Guide](https://www.quantconnect.com/docs/v2/writing-algorithms/key-concepts/research-guide): hypothesis-driven testing, look-ahead/survivorship bias, and overfitting guidance.
- [QuantConnect: ATR](https://www.quantconnect.com/docs/v2/writing-algorithms/indicators/supported-indicators/average-true-range): ATR measures smoothed true range and is useful as a volatility/risk input, not a standalone buy signal.
- [QuantConnect: Slippage](https://www.quantconnect.com/docs/v2/writing-algorithms/reality-modeling/slippage/key-concepts) and [Transaction Fees](https://www.quantconnect.com/docs/v2/writing-algorithms/reality-modeling/transaction-fees/key-concepts): realistic execution costs matter in backtests.

## 12. 2026-11-06 Log Review and Next-Version Diagnostics

The 2026-11-06 GitHub Actions run covered 1,609 scan cycles. It recorded 1,265 MIS hits, one effective 3K, 30 Fugle HTTP errors, one daily-score rejection, and no Telegram send attempts. The single effective 3K passed the 1.5x same-time volume flag but failed Tier 1's daily score gate. The log did not include that candidate's symbol, exact daily score, or daily bullish result, so the precise score deficit cannot be reconstructed from this run.

Scan cadence averaged 10.04 seconds (P95 about 10.01 seconds; maximum gap 21.60 seconds). Cycle runtime averaged 1.51 seconds (P95 7.53 seconds; maximum 13.87 seconds). Fugle call time averaged 0.34 seconds, with a maximum of 8.28 seconds. Thus occasional API errors exist, but the measured cadence does not support latency as the reason for zero alerts on this date; the observed 3K was rejected by the score gate.

Next-version changes add observability without changing entry thresholds:

- 3K no-signal results report the first failed condition: insufficient completed bars, K3 close not above K1/K2 highs, or K3 volume below its threshold.
- Fugle HTTP errors include their HTTP status code in the failed-symbol list.
- Each effective-3K/MA20 candidate logs daily score and pass/fail, daily bullish result, intraday score, K3 volume ratio, same-time ratio/availability, TDCC change, insider streak, tier, and final send decision.
- These details identify whether future low alert counts come from signal frequency or later filters. They intentionally do not relax any gate.
