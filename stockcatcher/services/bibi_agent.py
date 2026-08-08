"""
檔案位置：services/bibi_agent.py
功能說明：天機選股系統 - 專屬 AI 交易員「比鼻 (Bibi)」核心服務模組
架構亮點：
  1. 使用最新 gemini-3.6-flash 模型，確保在 Vercel 10 秒 Serverless 限制內完成高維度推理。
  2. 嚴格封裝 Prompt 與生成邏輯，與主程式 (Webhook) 完全解耦。
  3. 配置 GenerationConfig 防止長篇大論導致 Timeout。
"""

import os
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold, GenerationConfig

# ==========================================
# 🧠 1. 系統核心提示詞 (優化版：消除廢話，直奔主題)
# ==========================================
BIBI_SYSTEM_PROMPT = """
你是一名專業股市研究員、交易員，名叫比鼻。

【你的思考底層邏輯：Trend Core 聰明錢三層獨立確認】
(這只是你的思考框架，絕對不要在對話中向使用者背誦或解釋以下原則)
- L1：內部人足跡 (SEC Form 4, 13D/13G)
- L2：研究者足跡 (頂級經理人 13F 與公開推理)
- L3：結構性足跡 (板塊資金流向與 Capex)
你的工作流是：[尋找資金流向] ➔ [三層訊號找交集] ➔ [歷史回測與估值] ➔ [判斷時機]。

【嚴格回覆規範 - 絕對遵守】
1. 直奔主題：嚴禁任何開場白、寒暄（不要說你好）。
2. 拒絕廢話：絕對禁止向使用者重複或解釋「你的選股邏輯」、「不看新聞喊單」、「我們不談情緒」等理念。使用者已經懂了。
3. 數據說話：直接給出市場大盤、資金流向與板塊強弱的「客觀分析與結論」。
4. 結構化排版：使用 Markdown 條列式，適當使用 Emoji，保持專業冷靜。
"""

# ==========================================
# ⚙️ 2. LLM 服務初始化與推論邏輯
# ==========================================
def ask_bibi_agent(user_message: str) -> str:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return "比鼻系統異常（缺少通訊憑證）。"

    genai.configure(api_key=api_key)

    # 確保使用 gemini-1.5-flash 以兼顧速度
    model = genai.GenerativeModel(
        model_name="gemini-3.6-flash",
        system_instruction=BIBI_SYSTEM_PROMPT
    )

    try:
        safety_settings = {
            HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_ONLY_HIGH,
            HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_ONLY_HIGH,
            HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_ONLY_HIGH,
        }

        # ==========================================
        # 🎯 核心優化：Token 生成參數控制區塊
        # ==========================================
        generation_config = GenerationConfig(
            # 降低 temperature (0.4)：讓分析更精準客觀，杜絕發散式的廢話
            temperature=0.3,         
            # 放寬字數上限 (4096)：避免資料被截斷，完整呈現分析結果
            max_output_tokens=4096,   
        )

        response = model.generate_content(
            user_message,
            safety_settings=safety_settings,
            generation_config=generation_config
        )
        
        return response.text

    except Exception as e:
        error_msg = str(e)
        print(f"❌ [Bibi Agent 錯誤] {error_msg}")
        return "比鼻目前正在處理大量市場數據，腦袋有點過載了，請稍後再試或精簡您的問題！ 😵‍💫"
    