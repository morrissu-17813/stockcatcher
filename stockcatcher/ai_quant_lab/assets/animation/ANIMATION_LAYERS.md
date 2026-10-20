# 三層角色系統（v3）

## Layer 1 — Character Art
`dashboard/public/agents/*.webp` 是六位角色的基礎立繪。`assets/design/` 收錄角色／動作概念板作為美術規格參考。

## Layer 2 — Motion & FX
`preview.html` 的 `.motion-stage` 控制坐姿待機、工作點頭、站立回報、完成跳躍、警示傾身；`.motion-overlay` 顯示掃描、完成與警示特效。動畫以 CSS keyframes 播放，不依賴外部服務。

## Layer 3 — Runtime State Binding
`refresh()` 從 `/api/state` 讀取角色真實 `status` 與 `task`，綁定 `data-motion`：
- `idle` → 待機／坐下
- `working` → 依角色職能顯示工作動作
- `success` → 任務完成
- `warning` → 警示／拒絕

注意：目前是立繪加 CSS 動作表現，能呈現坐下沉降、工作點頭、站起回報、慶祝跳躍與警示傾身；還不是逐格手繪的骨架動畫。若要真正改變四肢姿勢，下一階段要為每隻狗補齊獨立的坐姿／站姿／工作姿／慶祝／警示透明 PNG 或 Lottie/Sprite Sheet。
