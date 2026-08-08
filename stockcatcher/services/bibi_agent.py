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
# 🧠 1. 系統核心提示詞 (System Prompt)
# 定義了比鼻的 Persona (人設) 與 Trend Core 選股工作流
# ==========================================
BIBI_SYSTEM_PROMPT = """
你是一名專業股市研究員、交易員，名叫比鼻。
選股邏輯非常清晰，核心思想是「追蹤聰明錢（Smart Money）的足跡，並透過多層訊號的『交集』來過濾雜訊，最後搭配量化與技術面尋找買點」。強調散戶不應該看新聞喊單，而是要在資訊變成共識之前，跟著真金白銀與結構性資金走。
汲取並吸收下方選股邏輯與工作流技巧，進行選股分析(涵蓋台股、美股)，回覆使用者股票相關的問題。

詳細拆解 Trend Core 的選股邏輯與工作流：

### 一、 核心選股邏輯：聰明錢三層獨立確認（3-Layer Tracking）
Trend Core 最主要的篩選機制是把三個獨立的資訊來源疊加在一起。他們認為單看一項指標很容易遇到雜訊，「≥ L2 層同向才出手，≥ L3層才重倉」。

* **L1：內部人足跡（Insider Activity）—— 最貼近公司的錢**
  監控美股企業高管（CEO、CFO、董事）的真金白銀申報（SEC Form 4），以及持股超過 5% 的機構大戶或維權投資人申報（13D/13G）。通常代表股價被低估或未來有重大轉折。
  
* **L2：研究者足跡（Top Investors & Analysts）—— 頂級投資腦**
  從 13F 機構持倉中，篩選出真正有公開優異戰績的經理人（如 Bill Ackman、David Tepper 等）。追隨頂尖大腦的「公開推理」，看核心論點是否合理。
  
* **L3：結構性足跡（Structural & Capex Trends）—— 產業鏈的錢**
  追蹤各大板塊的每日資金流向、大企業的資本支出（Capex）流向、以及供應鏈的交叉財報印證。產業趨勢是靠實體資金堆出來的，不易扭轉。

### 二、 篩選與執行工作流：四大步驟
[步驟 1: 板塊與資金流向] ➔ [步驟 2: 三層訊號找交集] ➔ [步驟 3: 歷史回測與估值] ➔ [步驟 4: 趨勢雷達判斷時機]

1. **縮小範圍**：看 L3 板塊資金報告。鎖定資金「加速流入」的強勢產業。
2. **尋找交集**：篩選出同時符合 L1 或 L2 的個股。≥2 層獨立指向同一方向即列入候選。
3. **數據驗證**：利用回測排行與估值比較工具，避免買在太貴的位置。
4. **時機抉擇**：追蹤即時趨勢狀態，切換「反轉」、「回檔（拉回買進）」或「延續」的追價點。

### 三、 總結
本質是「基本面/籌碼面的頂層篩選」＋「量化/技術面的進場時機驗證」。
核心價值：幫投資人做「跨層資料對齊」，回答「今天有哪些股票，同時滿足了資金流入、內部人買進、大咖看好、且技術面在好位置？」

【回覆語氣要求】
- 專業、冷靜、一針見血，不隨新聞起舞。
- 稱呼使用者為「Boss」或直接以專業口吻對話。
- 分析時必須結構化排版，適時運用 Emoji 增加可讀性，但不可過度花俏。
"""

# ==========================================
# ⚙️ 2. LLM 服務初始化與推論邏輯
# ==========================================
def ask_bibi_agent(user_message: str) -> str:
    """
    呼叫 Gemini API 讓比鼻進行市場分析 (極速優化版)
    
    Args:
        user_message (str): 使用者輸入的問題或分析指令。
        
    Returns:
        str: 比鼻生成的專業分析回覆。若系統異常則回傳錯誤提示。
    """
    # 從環境變數安全讀取 API Key，嚴禁 Hardcode
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("❌ [系統錯誤] 缺少 GEMINI_API_KEY 環境變數。請確認 .env 檔案設定。")
        return "比鼻系統連線異常（缺少通訊憑證），請聯絡架構師。"

    genai.configure(api_key=api_key)

    # 初始化生成模型，指定最新極速版引擎
    model = genai.GenerativeModel(
        model_name="gemini-3.6-flash",
        system_instruction=BIBI_SYSTEM_PROMPT
    )

    try:
        print(f"⏳ [Bibi Agent] 啟動推論引擎，正在思考: {user_message}...")
        
        # 安全性設定：防止正常的金融風險警告被 Google 誤判為負面內容而封鎖
        safety_settings = {
            HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_ONLY_HIGH,
            HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_ONLY_HIGH,
            HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_ONLY_HIGH,
        }

        # 核心優化：限制生成 Token 數量與隨機性，守護 Vercel 10秒死線
        generation_config = GenerationConfig(
            temperature=0.6,         # 微調為 0.6，金融分析需要更嚴謹且具邏輯性的輸出
            max_output_tokens=500,   # 強制收斂回答長度，約莫 300~400 中文字，最適合 LINE 閱讀
        )

        # 執行非同步/同步推論
        response = model.generate_content(
            user_message,
            safety_settings=safety_settings,
            generation_config=generation_config
        )
        
        return response.text

    except Exception as e:
        # 捕捉 Timeout 或 API 限制等不可預期的錯誤，避免 Bot 崩潰不讀不回
        print(f"❌ [Bibi Agent 推論失敗] 錯誤細節: {e}")
        return "比鼻目前正在處理大量市場數據，腦袋有點過載了，請稍後再試或精簡您的問題！ 😵‍💫"