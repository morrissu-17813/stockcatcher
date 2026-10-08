# CHANGELOG V1.2.1

## EARLY 盤中提前預警調整

- EARLY 條件正式改為：MIS 有效突破 + 兩個不同 data identity + 漲幅 >= 4% + Fugle 5M 結構/量能至少一項成立。
- Fugle 5M 改為回傳獨立的 `structure_pass` / `volume_pass`，不再要求兩者同時成立。
- EARLY 不再受 Projected Volume >= 1.30x 硬閘限制，避免錯過早期發動。
- STRONG：5M 結構 + 5M 量能同時成立，且 projected volume >= 1.30x。
- MOMENTUM：STRONG 條件成立且漲幅 >= 9.5%。
- EARLY Telegram 新增結構/量能明確標示：`✔` / `✖`，並使用定版文字「盤中提前預警，等待 STRONG 確認。」
- 同一股票同一天同一訊號等級只發送一次；EARLY 後續仍可升級為 STRONG / MOMENTUM。
- 保留原有 MIS、State Machine、Fugle、Projected Volume、GROUND_TRUTH 與 Telegram recovery chain。

## 測試

- Full pytest suite: 118 passed, 0 failed.
