# AI Quant Lab — 三層西施犬角色系統

1. 角色素材：`dashboard/public/agents/*.webp`；淺奶油中長毛、黑白中毛、金棕長毛、深咖啡中長毛、淺米短毛、雪白蓬鬆長毛。
2. 動作播放：`preview.html` 以 CSS keyframes 表現待機呼吸、工作點頭、站立回報、完成跳躍、警示傾身、掃描光與各角色專屬工作節奏。
3. 真實狀態連動：`preview.html` 每 2.5 秒讀取 `/api/state`，依 Agent status/task 設定 `data-motion`；只有 API 真正回報工作／完成／警示時才切換相應動畫。

限制：目前是完整立繪加 CSS 動作，不是逐格骨架動畫；要讓四肢真正換姿勢，需要後續為每個角色繪製透明背景分姿勢素材或 Lottie/Sprite Sheet。所有成交均為 paper trading。
