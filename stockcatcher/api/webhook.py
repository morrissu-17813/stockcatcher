# 檔案位置：api/webhook.py
import os
from datetime import datetime, timezone, timedelta
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
 
# 載入環境變數
load_dotenv()
 
app = FastAPI()
 
# ==========================================
# ⚙️ 環境變數與安全憑證配置
# ==========================================
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET", "")
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
 
configuration = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)
 
# 初始化 Supabase 客戶端
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
 
# ==========================================
# 💾 資料庫讀取與聚合層 (Data Access & Aggregation)
# ==========================================
def fetch_and_aggregate_signals(category: str) -> tuple[list, str]:
   """
   從 Supabase 獲取單行單標的 (Append-only) 訊號，並進行去重與聚合。
   回傳 Tuple: (聚合後的股票清單, 最後更新時間字串)
   """
   try:
       # 為了效能與記憶體考量，這裡我們限制撈取最新的 500 筆紀錄
       # 實務上線後，建議改為依據日期過濾 (例如只撈今日)
       response = supabase.table("tianji_signals") \
           .select("updated_at, data") \
           .eq("category", category) \
           .order("updated_at", desc=False) \
           .limit(500) \
           .execute()
 
       records = response.data
       if not records:
           return [], "尚無資料"
 
       stock_map = {}
       latest_time_str = "尚無資料"
 
       # 進行 O(N) 的高效去重與聚合
       for row in records:
           payload = row.get("data", {})
           if not isinstance(payload, dict):
               continue
               
           stock_id = payload.get("stock_id")
           if not stock_id:
               continue
 
           if stock_id in stock_map:
               current_count = stock_map[stock_id].get("notify_count", 0)
               # 後進覆寫，保證數據最新
               stock_map[stock_id] = payload
               stock_map[stock_id]["notify_count"] = current_count + 1
           else:
               stock_map[stock_id] = payload
               stock_map[stock_id]["notify_count"] = 1
               
           # 記錄最後一筆的更新時間
           raw_time = row.get("updated_at")
           if raw_time:
               latest_time_str = str(raw_time)[:16].replace("T", " ")
 
       aggregated_list = list(stock_map.values())
       
       # 商業邏輯排序：優先看通知次數 (遞減)，再看預估量比 (遞減)
       aggregated_list.sort(
           key=lambda x: (
               x.get("notify_count", 0),
               float(x.get("vol_ratio", 0.0) if x.get("vol_ratio") else 0)
           ),
           reverse=True
       )
 
       return aggregated_list, latest_time_str
 
   except Exception as e:
       print(f"❌ [DB 讀取與聚合錯誤] {e}")
       return [], "讀取錯誤"
 
# ==========================================
# 🧠 意圖解析層 (Intent Parsing Layer)
# ==========================================
def parse_user_intent(raw_msg: str) -> str:
   """將非結構化的自然語言收斂為標準的系統指令路由"""
   clean_msg = raw_msg.strip().replace(" ", "").replace(" ", "").lower()
 
   warrant_keywords = ["權證主力", "權證發動", "權證介入", "主力發動", "主力權證"]
   volume_3k_keywords = ["3k突破", "量能異常", "3k量能", "爆量", "3k發動"]
   tide_keywords = ["tide", "族群熱力", "資金流向", "最強族群"]
   dashboard_keywords = ["視覺儀表板", "儀表板", "開啟liff", "選股地圖"]
 
   if any(k in clean_msg for k in warrant_keywords): return "INTENT_WARRANT_3K"
   if any(k in clean_msg for k in volume_3k_keywords): return "INTENT_VOLUME_3K"
   if any(k in clean_msg for k in tide_keywords): return "INTENT_TIDE_HEATMAP"
   if any(k in clean_msg for k in dashboard_keywords): return "INTENT_DASHBOARD"
       
   return "INTENT_UNKNOWN"
 
# ==========================================
# 🎨 視覺渲染層 (Presentation Layer)
# ==========================================
def build_strategy_list_flex(title: str, signals: list, update_time: str) -> FlexContainer:
   """動態組裝 LINE Flex Message (單一列表卡片視圖)"""
   if not signals:
       return FlexContainer.from_dict({
           "type": "bubble", "size": "mega",
           "body": {
               "type": "box", "layout": "vertical",
               "contents": [{"type": "text", "text": f"{title} 目前尚無符合標的", "color": "#94a3b8", "weight": "bold"}]
           }
       })
 
   header_box = {
       "type": "box", "layout": "vertical", "backgroundColor": "#0f172a", "paddingAll": "16px",
       "contents": [
           {"type": "text", "text": title, "color": "#ffffff", "size": "lg", "weight": "bold"},
           {"type": "text", "text": f"最後更新: {update_time[-5:]}", "color": "#94a3b8", "size": "xs", "margin": "sm"}
       ]
   }
 
   body_contents = []
   for index, s in enumerate(signals):
       sid, name = s.get("stock_id", "N/A"), s.get("stock_name", "N/A")
       price, stop_loss = s.get("price", 0.0), s.get("stop_loss", 0.0)
       vol_ratio = s.get("vol_ratio", 0.0)
       industry, sub_industry = s.get("industry", "-"), s.get("sub_industry", "-")
       count = s.get("notify_count", 1)
 
       stock_row = {
           "type": "box", "layout": "vertical", "margin": "lg" if index > 0 else "none",
           "contents": [
               {
                   "type": "box", "layout": "horizontal",
                   "contents": [
                       {"type": "text", "text": f"{sid} {name}", "size": "md", "weight": "bold", "color": "#1e293b", "flex": 3},
                       {"type": "text", "text": f"通知 {count} 次", "size": "xs", "color": "#ef4444", "align": "end", "weight": "bold", "flex": 1}
                   ]
               },
               {"type": "text", "text": f"[{industry}] {sub_industry}", "size": "xs", "color": "#64748b", "margin": "sm"},
               {
                   "type": "box", "layout": "horizontal", "margin": "md",
                   "contents": [
                       {"type": "text", "text": f"現價: {price}", "size": "sm", "color": "#334155", "flex": 1},
                       {"type": "text", "text": f"量比: {vol_ratio}x", "size": "sm", "color": "#d97706", "weight": "bold", "flex": 1},
                       {"type": "text", "text": f"停損: {stop_loss}", "size": "sm", "color": "#334155", "flex": 1}
                   ]
               }
           ]
       }
       body_contents.append(stock_row)
       if index < len(signals) - 1:
           body_contents.append({"type": "separator", "margin": "lg", "color": "#e2e8f0"})
 
   return FlexContainer.from_dict({
       "type": "bubble", "size": "giga",
       "header": header_box,
       "body": {"type": "box", "layout": "vertical", "paddingAll": "16px", "contents": body_contents}
   })
 
# ==========================================
# 🌐 Webhook 路由與控制器 (Controller Layer)
# ==========================================
@app.post("/api/webhook")
async def callback(request: Request):
   """LINE 伺服器進件原生端點"""
   signature = request.headers.get("X-Line-Signature", "")
   body = await request.body()
   try:
       handler.handle(body.decode("utf-8"), signature)
   except InvalidSignatureError:
       raise HTTPException(status_code=400, detail="Invalid signature. 請檢查 LINE Secret。")
   return "OK"
 
@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
   """處理圖文選單按鈕觸發的查詢事件"""
   user_msg = event.message.text
   action_intent = parse_user_intent(user_msg)
   reply_flex = None
 
   if action_intent == "INTENT_WARRANT_3K":
       signals, update_time = fetch_and_aggregate_signals("warrant_3k")
       reply_flex = build_strategy_list_flex("🎫 權證主力發動", signals, update_time)
       
   elif action_intent == "INTENT_VOLUME_3K":
       signals, update_time = fetch_and_aggregate_signals("volume_3k")
       reply_flex = build_strategy_list_flex("🔥 3K 量能異常", signals, update_time)
       
   elif action_intent == "INTENT_TIDE_HEATMAP":
       # 預留給下一步開發：TIDE 族群熱力
       pass
       
   elif action_intent == "INTENT_DASHBOARD":
       # 預留給下一步開發：LIFF 視覺儀表板
       pass
 
   # 統一發送回覆
   if reply_flex:
       with ApiClient(configuration) as api_client:
           line_bot_api = MessagingApi(api_client)
           line_bot_api.reply_message(
               ReplyMessageRequest(
                   reply_token=event.reply_token,
                   messages=[FlexMessage(alt_text="已為您查詢最新策略標的", contents=reply_flex)]
               )
           )
