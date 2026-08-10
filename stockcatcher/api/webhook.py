# 檔案位置：api/webhook.py
 
import os
import traceback
from datetime import datetime, timezone, timedelta, time
from fastapi import FastAPI, Request, HTTPException
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
   Configuration,
   ApiClient,
   MessagingApi,
   ReplyMessageRequest,
   FlexMessage,
   TextMessage,
   FlexContainer
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent
from supabase import create_client, Client
from dotenv import load_dotenv
 
from services.bibi_agent import ask_bibi_agent
 
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
 
# 初始化 LINE API 與 Webhook Handler
configuration = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)
 
# 初始化 Supabase 客戶端
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
 
# ==========================================
# 💾 資料庫讀取與聚合層 (Data Access & Aggregation)
# ==========================================
def fetch_and_aggregate_signals(keyword: str) -> tuple[list, str]:
   """
   從 Supabase 獲取單行單標的 (Append-only) 訊號，並進行去重與聚合。
   使用 ilike 進行關鍵字模糊比對，精準夾出台灣時間今日的全日區間資料。
   """
   try:
       # 1. 取得台灣時間的今日起訖點
       tw_tz = timezone(timedelta(hours=8))
       tw_now = datetime.now(tw_tz)
       
       # 產出 ISO 8601 格式的今日邊界
       start_of_day = datetime.combine(tw_now.date(), time.min, tzinfo=tw_tz).isoformat()
       end_of_day = datetime.combine(tw_now.date(), time.max, tzinfo=tw_tz).isoformat()
 
       # 2. 執行資料庫查詢：改用 .ilike() 模糊比對，並夾出當日區間 (desc=True 確保最新)
       response = supabase.table("tianji_signals") \
           .select("updated_at, data") \
           .ilike("category", f"%{keyword}%") \
           .gte("updated_at", start_of_day) \
           .lte("updated_at", end_of_day) \
           .order("updated_at", desc=True) \
           .execute()
 
       records = response.data
       if not records:
           return [], "今日尚無資料"
 
       # 3. 效能優化：因為是降冪排序，第一筆 records[0] 絕對是最新時間，只需解析一次
       latest_time_str = "時間解析錯誤"
       raw_time = records[0].get("updated_at")
       if raw_time:
           try:
               iso_time_str = str(raw_time).replace("Z", "+00:00")
               utc_time = datetime.fromisoformat(iso_time_str)
               tw_time = utc_time.astimezone(tw_tz)
               latest_time_str = tw_time.strftime("%Y-%m-%d %H:%M")
           except ValueError as ve:
               print(f"⚠️ [時間解析警告] {ve}")
               latest_time_str = str(raw_time)[:16].replace("T", " ")
 
       # 4. 進行 O(N) 的高效去重與聚合
       stock_map = {}
       for row in records:
           payload = row.get("data", {})
           if not isinstance(payload, dict):
               continue
               
           stock_id = payload.get("stock_id")
           if not stock_id:
               continue
 
           if stock_id not in stock_map:
               # 第一次遇到該股號 (因為降冪排序，此為最新一筆)
               stock_map[stock_id] = payload
               stock_map[stock_id]["notify_count"] = 1
           else:
               # 後續遇到舊紀錄，只增加通知次數，不覆寫最新 payload
               stock_map[stock_id]["notify_count"] += 1
               
       aggregated_list = list(stock_map.values())
       
       # 5. 商業邏輯排序：優先看通知次數 (遞減)，再看預估量比 (遞減)
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
       print(traceback.format_exc())
       return [], "讀取錯誤"
 
# ==========================================
# 🧠 意圖解析層 (Intent Parsing Layer)
# ==========================================
def parse_user_intent(raw_msg: str) -> str:
   """將非結構化的自然語言收斂為標準的系統指令路由"""
   clean_msg = raw_msg.strip().replace(" ", "").lower()
 
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
   """
   動態組裝 LINE Flex Message
   (包含強制定型防護網，避免髒資料引發渲染崩潰)
   """
   # 處理空資料的預設卡片 (確保 JSON 結構符合 LINE 規範)
   if not signals:
       return FlexContainer.from_dict({
           "type": "bubble",
           "size": "mega",
           "body": {
               "type": "box", "layout": "vertical", "paddingAll": "24px",
               "contents": [
                   {"type": "text", "text": f"{title} 目前尚無符合標的", "color": "#94a3b8", "weight": "bold", "align": "center"}
               ]
           }
       })
 
   ITEMS_PER_PAGE = 5  
   MAX_BUBBLES = 12    
   
   chunks = [signals[i:i + ITEMS_PER_PAGE] for i in range(0, len(signals), ITEMS_PER_PAGE)]
   if len(chunks) > MAX_BUBBLES:
       chunks = chunks[:MAX_BUBBLES]
 
   carousel_bubbles = []
 
   for page_index, chunk in enumerate(chunks):
       page_title = f"{title} ({page_index + 1}/{len(chunks)})" if len(chunks) > 1 else title
       
       header_box = {
           "type": "box", "layout": "vertical", "backgroundColor": "#FAF5F0", "paddingAll": "16px",
           "contents": [
               {"type": "text", "text": page_title, "color": "#5C544E", "size": "md", "weight": "bold"},
               {"type": "text", "text": f"最後更新: {update_time[-5:]}", "color": "#A8A29E", "size": "xs", "margin": "xs"}
           ]
       }
 
       body_contents = []
       
       for item_index, s in enumerate(chunk):
           sid = str(s.get("stock_id", "N/A"))
           name = str(s.get("stock_name", "N/A"))
           industry = str(s.get("industry", "-"))
           
           # 🛡️ 核心防護網：強制轉型，防止資料庫內的 null 或錯誤字串引發伺服器崩潰
           try:
               price = float(s.get("price", 0.0) or 0.0)
               pct = float(s.get("pct", 0.0) or 0.0)
               vol_ratio = float(s.get("vol_ratio", 0.0) or 0.0)
               stop_loss = float(s.get("stop_loss", 0.0) or 0.0)
               count = int(s.get("notify_count", 1) or 1)
           except (ValueError, TypeError):
               price, pct, vol_ratio, stop_loss, count = 0.0, 0.0, 0.0, 0.0, 1
 
           price_color = "#f43f5e" if pct > 0 else ("#10b981" if pct < 0 else "#94a3b8")
           
           if count >= 5:
               count_color = "#f43f5e"  
           elif 2 <= count <= 4:
               count_color = "#f97316"  
           else:
               count_color = "#eab308"  
 
           stock_row = {
               "type": "box", "layout": "vertical", "margin": "lg" if item_index > 0 else "none",
               "contents": [
                   {
                       "type": "box", "layout": "horizontal",
                       "contents": [
                           {
                               "type": "text", "text": f"{sid} {name}", "size": "md", "weight": "bold",
                               "color": "#3b82f6", "decoration": "underline", "flex": 1,
                               "action": {
                                   "type": "uri", "label": "查看走勢",
                                   "uri": f"https://www.nstock.tw/stock_info?stock_id={sid}"
                               }
                           },
                           {
                               "type": "text", "text": f"{price} ({pct:+g}%)", "size": "md",
                               "color": price_color, "align": "end", "weight": "bold", "flex": 1
                           }
                       ]
                   },
                   {
                       "type": "box", "layout": "horizontal", "margin": "sm",
                       "contents": [
                           {"type": "text", "text": f"{industry}", "size": "xs", "color": "#94a3b8", "flex": 1},
                           {"type": "text", "text": f"量比: {vol_ratio}x", "size": "xs", "color": "#d97706", "align": "end", "flex": 1}
                       ]
                   },
                   {
                       "type": "box", "layout": "horizontal", "margin": "xs",
                       "contents": [
                           {"type": "text", "text": f"停損: {stop_loss}", "size": "xs", "color": "#64748b", "flex": 1},
                           {"type": "text", "text": f"通知 {count} 次", "size": "xs", "color": count_color, "align": "end", "weight": "bold", "flex": 1}
                       ]
                   }
               ]
           }
           body_contents.append(stock_row)
           
           if item_index < len(chunk) - 1:
               body_contents.append({"type": "separator", "margin": "lg", "color": "#f1f5f9"})
 
       carousel_bubbles.append({
           "type": "bubble", "size": "mega",
           "header": header_box,
           "body": {"type": "box", "layout": "vertical", "paddingAll": "16px", "backgroundColor": "#ffffff", "contents": body_contents}
       })
 
   return FlexContainer.from_dict({
       "type": "carousel",
       "contents": carousel_bubbles
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
   except Exception as e:
       # 🛡️ 捕捉 FastAPI 頂層錯誤並印出詳細堆疊
       print(f"❌ [系統嚴重崩潰] {e}")
       print(traceback.format_exc())
       raise HTTPException(status_code=500, detail="Internal Server Error")
   return "OK"
 
@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
   """處理使用者對話與圖文選單按鈕觸發的查詢事件"""
   user_msg = event.message.text.strip()
   
   # ==========================================
   # 🤖 路由 1：攔截專屬 AI 交易員「比鼻」的動態對話
   # ==========================================
   if user_msg.startswith("Hi 比鼻"):
       query = user_msg.replace("Hi 比鼻", "").strip()
       if query.startswith("，") or query.startswith(","):
           query = query[1:].strip()
           
       if not query or "資金" in query or "大盤" in query or "流向" in query:
           query = "請深入剖析目前美股與台股大盤概況，並詳細列舉強勢板塊與弱勢板塊的資金流向、驅動因素與機構動態。"
 
       ai_reply = ask_bibi_agent(query)
       
       with ApiClient(configuration) as api_client:
           line_bot_api = MessagingApi(api_client)
           line_bot_api.reply_message(
               ReplyMessageRequest(
                   reply_token=event.reply_token,
                   messages=[TextMessage(text=ai_reply)]
               )
           )
       return
 
   # ==========================================
   # 📊 路由 2：圖文選單靜態意圖解析 (Flex Message)
   # ==========================================
   action_intent = parse_user_intent(user_msg)
   reply_flex = None
   
   if action_intent == "INTENT_WARRANT_3K":
       signals, update_time = fetch_and_aggregate_signals("權證")
       reply_flex = build_strategy_list_flex("🎫 權證主力發動", signals, update_time)
       
   elif action_intent == "INTENT_VOLUME_3K":
       signals, update_time = fetch_and_aggregate_signals("3K")
       reply_flex = build_strategy_list_flex("🔥 3K 量能異常", signals, update_time)
       
   elif action_intent == "INTENT_TIDE_HEATMAP":
       pass
       
   elif action_intent == "INTENT_DASHBOARD":
       pass
 
   # ==========================================
   # 📤 統一發送 Flex Message 回覆
   # ==========================================
   if reply_flex:
       try:
           with ApiClient(configuration) as api_client:
               line_bot_api = MessagingApi(api_client)
               line_bot_api.reply_message(
                   ReplyMessageRequest(
                       reply_token=event.reply_token,
                       messages=[FlexMessage(alt_text="已為您查詢最新策略標的", contents=reply_flex)]
                   )
               )
       except Exception as e:
           # 🛡️ 攔截 LINE API 回傳的 400 Bad Request (通常是 Flex 格式錯誤)
           print(f"❌ [LINE API 發送失敗] Flex 格式錯誤: {e}")
           print(traceback.format_exc())
           
           # 降級處理：改發送純文字，確保使用者知道系統狀態
           with ApiClient(configuration) as api_client:
               line_bot_api = MessagingApi(api_client)
               line_bot_api.reply_message(
                   ReplyMessageRequest(
                       reply_token=event.reply_token,
                       messages=[TextMessage(text="抱歉，資料讀取成功，但在繪製卡片時發生格式錯誤，請通知工程師修復！")]
                   )
               )
