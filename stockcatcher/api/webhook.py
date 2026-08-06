# 檔案位置：api/webhook.py
import os
from fastapi import FastAPI, Request, HTTPException
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    ReplyMessageRequest,
    FlexMessage,
    FlexContainer
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()

# ==========================================
# ⚙️ 環境變數與安全憑證配置
# ==========================================
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET", "")
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
# 讀取端只需使用 anon key 即可 (防護性設計：讀寫權限分離)
# 但因為我們目前設定未開放 RLS，這裡先沿用 SERVICE_ROLE_KEY 或你的 Anon Key
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "") 

configuration = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# 初始化 Supabase 客戶端
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ==========================================
# 💾 資料庫讀取層 (Data Access Layer)
# ==========================================
def fetch_signals_from_supabase(category: str) -> list:
    """從 Supabase 瞬間撈取特定策略的最新標的"""
    try:
        response = supabase.table("tianji_signals").select("data").eq("category", category).execute()
        if response.data and len(response.data) > 0:
            return response.data[0].get("data", [])
        return []
    except Exception as e:
        print(f"❌ [DB 讀取錯誤] {e}")
        return []

def get_last_update_time(category: str) -> str:
    """獲取該策略最後更新時間"""
    try:
        response = supabase.table("tianji_signals").select("updated_at").eq("category", category).execute()
        if response.data and len(response.data) > 0:
            # 轉換為容易閱讀的格式 (可依需求調整 timezone)
            raw_time = response.data[0].get("updated_at")
            return str(raw_time)[:16].replace("T", " ")
        return "尚無資料"
    except:
        return "未知時間"

# ==========================================
# 🌐 Webhook 路由與業務邏輯
# ==========================================
@app.post("/callback")
async def callback(request: Request):
    """LINE 伺服器進件端點"""
    signature = request.headers.get("X-Line-Signature", "")
    body = await request.body()
    body_str = body.decode("utf-8")

    try:
        handler.handle(body_str, signature)
    except InvalidSignatureError:
        raise HTTPException(status_code=400, detail="Invalid signature. 請檢查 LINE Secret。")
    return "OK"

@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    """處理圖文選單按鈕觸發的查詢事件"""
    user_msg = event.message.text.strip()
    reply_flex = None

    # 🎯 路由分發：依據使用者點擊的指令，向 Supabase 請求對應資料
    if user_msg == "【查詢】當前 權證主力+3K 突破":
        signals = fetch_signals_from_supabase("warrant_3k")
        # 測試階段如果沒有資料，我們抓剛才測試用的資料來展示
        if not signals:
             signals = fetch_signals_from_supabase("test_signal")
             
        update_time = get_last_update_time("warrant_3k")
        reply_flex = build_minimalist_carousel("🎫 權證主力發動", signals, update_time)
        
    elif user_msg == "【查詢】當前 3K 突破+量能異常":
        signals = fetch_signals_from_supabase("volume_3k")
        update_time = get_last_update_time("volume_3k")
        reply_flex = build_minimalist_carousel("🔥 3K 量能異常", signals, update_time)
        
    # 如果有產生 Flex 卡片，則透過 Reply API 秒回
    if reply_flex:
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[FlexMessage(alt_text=user_msg, contents=reply_flex)]
                )
            )

# ==========================================
# 🎨 視覺渲染層 (Presentation Layer)
# ==========================================
def build_minimalist_carousel(title: str, signals: list, update_time: str) -> FlexContainer:
    """動態組裝 LINE Flex Message"""
    if not signals:
        return FlexContainer.from_dict({
            "type": "bubble",
            "body": {
                "type": "box", "layout": "vertical",
                "contents": [{"type": "text", "text": "目前尚無符合條件的標的", "color": "#94a3b8"}]
            }
        })

    bubbles = []
    for s in signals:
        sid, name = s.get("sid", "N/A"), s.get("name", "N/A")
        lp, pct = s.get("lp", 0), s.get("pct", 0)
        pct_color = "#ef4444" if float(pct) > 0 else "#22c55e" 
        
        bubble = {
            "type": "bubble",
            "size": "micro", 
            "header": {
                "type": "box", "layout": "vertical", "backgroundColor": "#0f172a", "paddingAll": "12px",
                "contents": [
                    {"type": "text", "text": title, "color": "#94a3b8", "size": "xxs", "weight": "bold"},
                    {"type": "text", "text": f"{sid} {name}", "color": "#ffffff", "size": "md", "weight": "bold", "margin": "md"}
                ]
            },
            "body": {
                "type": "box", "layout": "vertical", "paddingAll": "12px",
                "contents": [
                    {"type": "text", "text": str(lp), "size": "xl", "weight": "bold", "color": "#1e293b"},
                    {"type": "text", "text": f"{pct}%", "size": "sm", "weight": "bold", "color": pct_color},
                    {"type": "separator", "margin": "md"},
                    {"type": "text", "text": f"更新: {update_time[-5:]}", "size": "xxs", "color": "#94a3b8", "margin": "md"}
                ]
            }
        }
        bubbles.append(bubble)

    return FlexContainer.from_dict({"type": "carousel", "contents": bubbles[:12]}) # LINE Carousel 上限 12 張