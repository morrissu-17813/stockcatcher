# 天機 3K Stage 1 Trend Engine

Input: Stage 0 Production JSON where `final_stage0_pass=true`.

Conditions are exactly: Close > MA20, Close > MA60, MA20 > MA60, MA20(K0) > MA20(K1).
K0 is the latest completed daily bar available in the local cache. Missing 61-bar history is UNKNOWN, not FAIL/PASS.

Example:
`python -m tianji_3k.stage1.trend_engine --stage0-json tianji_3k/cache/stage0_production.json --cache-dir tianji_3k/cache/daily --csv tianji_3k/cache/stage1_trend.csv --json tianji_3k/cache/stage1_trend.json`
