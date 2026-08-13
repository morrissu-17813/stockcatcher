# 檔案位置：services/bibi_agent.py

import os
import json
import re
import traceback
from datetime import datetime, timezone, timedelta

# 全面採用最新版 google.genai 官方 SDK
from google import genai
from google.genai import types

# ==========================================
# 🤖 [專家 1] 資金流向與市場大盤 Prompt (Trend Core)
# ==========================================
BIBI_FLOW_PROMPT_TEMPLATE = """
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
"""

# ==========================================
# 🤖 [專家 2] 單一個股基本面與目標價 Prompt (余森山天機圖心法)
# ==========================================
BIBI_FUNDAMENTAL_PROMPT_TEMPLATE = """
你是一個專業股市量化交易研究分析師，名叫比鼻。你鑽研余森山老師的「股市天機圖操盤法」，融會貫通後提供股票分析結果。

【當前時間錨點】
現在時間：{current_date_str}。請務必使用最新數據資料。

【任務說明與輸出結構】
當使用者要求分析某檔股票時，請參考「天機圖操盤法」的心法，並【嚴格】依照下方的結構與表格進行回應：

針對 [股票名稱] 這檔股票，這是一家專精於 [核心業務與產業地位] 的利基型大廠/公司。目前正處於 [營運現狀簡述] 的階段。

以下為您進行詳細分析：
## 1. 財務與營運現況 (近一年與未來)
[股票名稱] 的產品主要分為 [說明主要產品線]：
* 去年回顧： [說明全年 EPS 與獲利表現概況，如是否倒吃甘蔗等]
* 最新動態： [說明今年最新月份營收、年增率或新高紀錄]
* 產能/營運狀況： [說明產能稼動率、訂單狀況或未來展望]

## 2. 核心競爭力分析
[股票名稱] 並非一般公司，其優勢在於：
* [優勢 1 標題]： [詳細說明，如國際認證、高毛利等]
* [優勢 2 標題]： [詳細說明，如產品組合優化]

## 3. 股利與價值評估
* 股利政策： [說明配息狀況與估算現金殖利率]
* 本益比 (P/E)： [說明目前估值，評估是否合理或偏低]
* 供應鏈角色： [說明屬於哪種供應鏈的上中下游？是什麼題材族群性？合作夥伴是誰？]

## 4. 技術面與籌碼面
* 技術面： [說明股價近期走勢、重要關卡、短期均線狀態及技術指標]
* 籌碼面： [說明外資、投信或大戶持股比例等籌碼集中度狀態]

### 總結分析表
| 項目 | 評價 (🟢強/🟡平/🔴弱) | 關鍵說明 |
| :--- | :---: | :--- |
| 成長性 | [評價] | [說明產能或營收狀況] |
| 獲利結構 | [評價] | [說明毛利或產品組合] |
| 股利政策 | [評價] | [說明配息與殖利率] |
| 技術趨勢 | [評價] | [說明均線與籌碼狀態] |

💡 投資建議：
[提供投資心法建議，並根據國際情勢、大盤狀態等給出建議]

💡 目標價 (近1~3年)：
| 期間 | 預估目標價格區間 | 爆發性成長優勢 / 潛在催化劑 |
| :--- | :--- | :--- |
| 1年內 | [預估價格區間] | [簡述相關爆發性成長優勢] |
| 2-3年 | [預估價格區間] | [簡述長線催化劑] |

-------------------
使用者提問：「{user_query}」
"""

# ==========================================
# 🤖 [專家 3] 生活與新知專家 Prompt (非股票類)
# ==========================================
BIBI_GENERAL_LIFE_PROMPT_TEMPLATE = """
你是一個食衣住行育樂樣樣精通的專家，在士農工商等領域都有著墨，經濟趨勢發展觀察家，各種產業面的研究學者，名叫比鼻。走遍大江南北，遊歷過全世界，熟悉熱門旅遊景點。你懂生活、懂人情世故，喜追求新知與新鮮事物的人。
 
【當前時間錨點】
現在時間：{current_date_str}。
 
【回覆規範】
1. 展現熱情、幽默、有品味且富有同理心的語氣。
2. 分享生活風格、美食、旅遊、科技新知或人際關係建議時，給出具體且獨到的見解。
3. 若使用者抱怨或分享心情，請給予溫暖的傾聽與具人情味的回應。
4. 適當使用 重點條列式 與 Emoji 讓版面豐富有趣，像是一位有質感的知心好友。
 
-------------------
使用者提問：「{user_query}」
"""

# ==========================================
# 🚦 意圖與模板註冊表 (Prompt Registry)
# ==========================================
PROMPT_REGISTRY = {
    "INTENT_FLOW_ANALYSIS": BIBI_FLOW_PROMPT_TEMPLATE,
    "INTENT_STOCK_FUNDAMENTAL": BIBI_FUNDAMENTAL_PROMPT_TEMPLATE,
    "INTENT_GENERAL_LIFE": BIBI_GENERAL_LIFE_PROMPT_TEMPLATE,
}

# ==========================================
# 🧠 LLM 意圖解析器 (Semantic Router Prompt)
# ==========================================
INTENT_ROUTER_PROMPT = """
你是一個後端系統的「自然語言意圖分類器」(Semantic Router)。
請分析使用者的對話，判斷其意圖，並嚴格輸出合法的 JSON 格式。

【支援的意圖清單】
1. "INTENT_FLOW_ANALYSIS" : 詢問市場大盤、板塊熱度、資金流向、大方向盤勢。
2. "INTENT_STOCK_FUNDAMENTAL" : 詢問「單一或特定股票」的基本面、分析、目標價、是否可買進。
3. "INTENT_GENERAL_LIFE" : 一般閒聊、食衣住行、心情分享、非股市相關的問題。

【輸出 JSON 格式】
{{"intent": "上述三種意圖之一", "stock_name": "若詢問特定個股請萃取股名，否則填 null"}}

使用者：「{user_query}」
輸出：
"""

# ==========================================
# ⚙️ 核心 AI 呼叫封裝層 (容錯降級機制)
# ==========================================
_client = None  # 模組級單例，避免每次請求都重新建立 Client 與底層連線

def _get_client() -> genai.Client:
    global _client
    if _client is None:
        # 預設自環境變數  提取金鑰
        _client = genai.Client()
    return _client

# LINE webhook 對回覆時間敏感，避免單次呼叫無限期卡住
_REQUEST_TIMEOUT_MS = 30_000

def _build_config(is_router: bool, thinking_level: "types.ThinkingLevel") -> "types.GenerateContentConfig":
    safety_settings = [
        types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_HARASSMENT, threshold=types.HarmBlockThreshold.BLOCK_ONLY_HIGH),
        types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_HATE_SPEECH, threshold=types.HarmBlockThreshold.BLOCK_ONLY_HIGH),
        types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT, threshold=types.HarmBlockThreshold.BLOCK_NONE),
        types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT, threshold=types.HarmBlockThreshold.BLOCK_ONLY_HIGH),
    ]
    return types.GenerateContentConfig(
        response_mime_type="application/json" if is_router else "text/plain",
        safety_settings=safety_settings,
        # 意圖分類需要穩定輸出，固定 temperature=0 避免同一句話判斷出不同意圖
        temperature=0 if is_router else None,
        thinking_config=types.ThinkingConfig(thinking_level=thinking_level),
        http_options=types.HttpOptions(timeout=_REQUEST_TIMEOUT_MS),
    )

def _extract_text(response) -> str:
    # 安全攔截或空候選會讓 response.text 為 None，直接 strip() 會拋未分類例外
    text = getattr(response, "text", None)
    if not text:
        raise ValueError("模型回傳內容為空 (可能觸發安全攔截或無候選結果)")
    return text.strip()

def _generate_with_fallback(prompt_text: str, is_router: bool = False) -> str:
    """
    負責呼叫 Gemini API，並處理 3.6-flash 與 3.5-flash-lite 的無縫雙軌降級。
    """
    client = _get_client()

    # --------------------------------------------------
    # 🚀 策略 A: Primary Model (gemini-3.6-flash)
    # --------------------------------------------------
    primary_model = 'gemini-3.6-flash'
    # 路由時使用 MINIMAL 極速決策，產生報告時使用 MEDIUM 深度推理
    primary_config = _build_config(
        is_router,
        types.ThinkingLevel.MINIMAL if is_router else types.ThinkingLevel.MEDIUM
    )

    try:
        response = client.models.generate_content(
            model=primary_model,
            contents=prompt_text,
            config=primary_config
        )
        return _extract_text(response)
        
    except Exception as primary_e:
        print(f"⚠️ [模型降級] {primary_model} 呼叫失敗: {str(primary_e)}")
        print("🔄 啟動備援模型切換程序：無縫切換至 gemini-3.5-flash-lite ...")
        
        # --------------------------------------------------
        # 🛡️ 策略 B: Fallback Model (gemini-3.5-flash-lite)
        # --------------------------------------------------
        fallback_model = 'gemini-3.5-flash-lite'
        # 備援模型一律採用 MINIMAL 確保極速與節省運算成本
        fallback_config = _build_config(is_router, types.ThinkingLevel.MINIMAL)
        
        try:
            fallback_response = client.models.generate_content(
                model=fallback_model,
                contents=prompt_text,
                config=fallback_config
            )
            return _extract_text(fallback_response)
            
        except Exception as fallback_e:
            print(f"❌ [備援失敗] {fallback_model} 亦無法連線。")
            raise fallback_e  # 往上拋給主程式做 429 友善攔截

# ==========================================
# 🚀 主控程式 (Agent Controller)
# ==========================================
def ask_bibi_agent(user_query: str, force_intent: str | None = None) -> str:
    """
    高擴展性的 AI Agent 執行器：負責意圖解析與專家 Prompt 分發
    """
    tw_tz = timezone(timedelta(hours=8))
    current_date_str = datetime.now(tw_tz).strftime("%Y年%m月%d日 %H:%M (台灣時間)")

    try:
        # ==========================================
        # ⚡ 階段一：意圖解析 (支援靜態強制路由)
        # ==========================================
        if force_intent:
            user_intent = force_intent
            print(f"⚡ [靜態路由] 觸發強制意圖注入: {user_intent}，節省一次 API 呼叫")
        else:
            router_response_text = _generate_with_fallback(
                INTENT_ROUTER_PROMPT.format(user_query=user_query), 
                is_router=True
            )
            
            # 🛡️ 安全脫殼：防禦模型偶爾回傳含有 ```json ... ``` 的 Markdown 區塊 (含前後多餘空白/換行)
            cleaned_text = router_response_text.strip()
            if cleaned_text.startswith("```"):
                cleaned_text = re.sub(r"^```(json)?\s*|\s*```$", "", cleaned_text.strip(), flags=re.IGNORECASE)
            router_response_text = cleaned_text.strip()

            intent_data = json.loads(router_response_text)
            user_intent = intent_data.get("intent", "INTENT_GENERAL_LIFE")
            stock_name = intent_data.get("stock_name")
            
            print(f"🔍 [AI 路由分析] 判定意圖: {user_intent} | 萃取實體: {stock_name}")

        # ==========================================
        # 📂 階段二：動態指派對應專家 Prompt
        # ==========================================
        selected_template = PROMPT_REGISTRY.get(user_intent, BIBI_GENERAL_LIFE_PROMPT_TEMPLATE)

        # 將使用者問題與當下時間注入選定的模板中
        final_prompt = selected_template.format(
            current_date_str=current_date_str,
            user_query=user_query
        )

        # ==========================================
        # 🚀 階段三：生成最終分析 (啟動降級容錯機制)
        # ==========================================
        final_response_text = _generate_with_fallback(final_prompt, is_router=False)
        
        return final_response_text

    except json.JSONDecodeError:
        print("❌ [意圖解析錯誤] LLM 回傳了非 JSON 格式的內容")
        return "比鼻剛剛腦袋卡住了，可以換個方式再問我一次嗎？ 😵‍💫"
    
    except Exception as e:
        error_msg = str(e)
        
        # 🛡️ 最終防護網：精準攔截雙模型皆耗盡額度的 429 錯誤
        if "429" in error_msg or "ResourceExhausted" in error_msg or "Quota exceeded" in error_msg:
            print(f"⚠️ [API 限流保護] 雙重模型皆觸發限流: {error_msg}")
            return "比鼻目前被太多人呼叫，雙核心系統都在塞車中 🚦 請大約等 1 到 2 分鐘，讓系統冷卻一下再問我喔！"
            
        print(f"❌ [Bibi Agent 錯誤] {error_msg}")
        print(traceback.format_exc())
        return "比鼻目前正在處理大量資訊，網路有點過載了，請稍後再試！ 😵‍💫"

