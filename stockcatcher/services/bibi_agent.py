# 檔案位置：services/bibi_agent.py
 
import os
import traceback
from datetime import datetime, timezone, timedelta
 
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold, GenerationConfig
 
# ==========================================
# 🤖 Bibi 系統核心設定 (System Prompt Template)
# 結合 Trend Core 邏輯、嚴格回覆規範與時間動態注入
# ==========================================
BIBI_SYSTEM_PROMPT_TEMPLATE = """
你是一名專業股市研究員、交易員，名叫比鼻。
 
【當前時間錨點】
現在的真實時間是：{current_date_str}。
你的所有市場分析、資金流向與標的推薦，都必須絕對基於此時間點進行推論，絕不可提供過期或錯誤的日期資訊。
 
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
5. 推薦：根據國際資金流向與板塊強弱，給出「台股、美股標的推薦、潛在黑馬股，至少各5檔」。
 
-------------------
【使用者的真實提問】
{user_query}
"""
 
def ask_bibi_agent(user_query: str) -> str:
   """
   接收 LINE 前端傳來的問題，注入時間上下文與 Trend Core 系統提示，
   並發送給 Gemini 進行推理。
   """
   try:
       # 獲取精確的台灣當前時間
       tw_tz = timezone(timedelta(hours=8))
       now = datetime.now(tw_tz)
       current_date_str = now.strftime("%Y年%m月%d日 %H:%M (台灣時間)")
 
       # 將時間與使用者問題動態填入系統模板
       final_prompt = BIBI_SYSTEM_PROMPT_TEMPLATE.format(
           current_date_str=current_date_str,
           user_query=user_query
       )
 
       # 初始化模型
       model = genai.GenerativeModel('gemini-1.5-pro')
 
       # 安全性設定 (配合金融分析需求，維持原本的配置)
       safety_settings = {
           HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_ONLY_HIGH,
           HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_ONLY_HIGH,
           HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
           HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_ONLY_HIGH,
       }
 
       # 生成參數控制：降低發散，提升邏輯嚴謹度
       generation_config = GenerationConfig(
           temperature=0.3,        
           max_output_tokens=4096,  
       )
 
       # 發送請求至大語言模型
       response = model.generate_content(
           final_prompt,
           safety_settings=safety_settings,
           generation_config=generation_config
       )
       
       return response.text
 
   except Exception as e:
       print(f"❌ [Bibi Agent 錯誤] {e}")
       print(traceback.format_exc())
       return "比鼻目前正在處理大量市場數據，腦袋有點過載了，請稍後再試或精簡您的問題！ 😵‍💫"
