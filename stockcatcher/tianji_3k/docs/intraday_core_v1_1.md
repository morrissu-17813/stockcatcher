# 天機 3K Intraday Core V1.1

## Scope

本版本只強化三個核心：

1. Intraday 3K breakout confirmation
2. Intraday volume projection
3. Explainable Prediction Score

SMC 金蛋蛋與 2TON 結構引擎不在本版本範圍。

## Volume Projection

- session: 09:00~13:30 = 270 minutes
- minimum elapsed time: 5 minutes
- projected volume = cumulative lots × 270 / elapsed minutes
- projected ratio = projected volume / VMA5 lots
- prediction volume gate: projected ratio >= 1.5x
- before 5 minutes: projection is not ready and ratio is None

## Prediction Score

Score is an explainable 0~100 index, not a probability.

- Trend: 30
  - MA20 > MA60: 20
  - MA20 slope up: 10
- Breakout: 30
  - effective breakout: 20
  - two confirmed distinct snapshots: 10
- Volume: 30
  - linear mapping around projected ratio 1.0~2.0x, capped at 30
- Price: 10
  - up >= 4%: 5
  - price > previous close: 5

Probability calibration is intentionally deferred until Prediction -> Ground Truth has enough historical observations.
