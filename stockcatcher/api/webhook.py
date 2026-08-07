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
                try:
                    # 1. 處理 Supabase 可能回傳的結尾 "Z" 或 "+00:00"
                    # 將字串轉換為具有時區意識 (Timezone-aware) 的 datetime 物件
                    iso_time_str = str(raw_time).replace("Z", "+00:00")
                    utc_time = datetime.fromisoformat(iso_time_str)
                    
                    # 2. 定義台灣時區 (UTC+8)
                    tw_tz = timezone(timedelta(hours=8))
                    
                    # 3. 進行時區轉換
                    tw_time = utc_time.astimezone(tw_tz)
                    
                    # 4. 格式化為易讀的字串 (YYYY-MM-DD HH:MM)
                    latest_time_str = tw_time.strftime("%Y-%m-%d %H:%M")
                except ValueError as ve:
                    # 容錯處理：若時間格式解析失敗，退回原始字串切片，確保系統不崩潰
                    print(f"⚠️ [時間解析警告] {ve}")
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
# 檔案位置：api/webhook.py
# 檔案位置：api/webhook.py

def build_strategy_list_flex(title: str, signals: list, update_time: str) -> FlexContainer:
    """
    動態組裝 LINE Flex Message 
    (無印櫻花奶茶系：支援大資料量的輪播卡片 Carousel)
    """
    # 1. 查無資料防呆：回傳單一 Bubble 提示空狀態
    if not signals:
        return FlexContainer.from_dict({
            "type": "bubble", "size": "mega",
            "body": {
                "type": "box", "layout": "vertical", "paddingAll": "24px",
                "contents": [
                    {"type": "text", "text": f"{title} 目前尚無符合標的", "color": "#94a3b8", "weight": "bold", "align": "center"}
                ]
            }
        })

    # ==========================================
    # ⚙️ 核心演算法：資料分頁分塊 (Pagination Chunking)
    # 考量使用者體驗與 LINE API 限制 (單一 Carousel 最多 10-12 個 Bubble)
    # ==========================================
    ITEMS_PER_PAGE = 10
    MAX_BUBBLES = 10  
    
    # 利用 Python 切片將一維陣列切割為二維陣列 (每個子陣列最多包含 10 筆資料)
    chunks = [signals[i:i + ITEMS_PER_PAGE] for i in range(0, len(signals), ITEMS_PER_PAGE)]
    
    # 系統邊界防護：截斷超過上限的分頁，確保 Payload 符合 LINE 的 300KB 限制
    if len(chunks) > MAX_BUBBLES:
        chunks = chunks[:MAX_BUBBLES]

    carousel_bubbles = []

    # ==========================================
    # 🧱 遍歷每一個資料塊，產生獨立的分頁 Bubble
    # ==========================================
    for page_index, chunk in enumerate(chunks):
        
        # 動態標題：若超過一頁，自動加上頁碼標示 (例如：權證主力發動 (1/3))
        page_title = f"{title} ({page_index + 1}/{len(chunks)})" if len(chunks) > 1 else title
        
        # 🎨 卡片頭部 (無印系櫻花奶茶色盤：溫潤淺奶茶 #FAF5F0 + 暖灰棕 #5C544E)
        header_box = {
            "type": "box", "layout": "vertical", "backgroundColor": "#FAF5F0", "paddingAll": "20px",
            "contents": [
                {"type": "text", "text": page_title, "color": "#5C544E", "size": "lg", "weight": "bold"},
                {"type": "text", "text": f"最後更新: {update_time[-5:]}", "color": "#A8A29E", "size": "xs", "margin": "sm"}
            ]
        }

        body_contents = []
        
        # 遍歷當前分頁內的單檔股票資料
        for item_index, s in enumerate(chunk):
            # 資料提取與預設值防呆
            sid = s.get("stock_id", "N/A")
            name = s.get("stock_name", "N/A")
            price = s.get("price", 0.0)
            pct = s.get("pct", 0.0)
            vol_ratio = s.get("vol_ratio", 0.0)
            stop_loss = s.get("stop_loss", 0.0)
            industry = s.get("industry", "-")
            sub_industry = s.get("sub_industry", "-")
            count = s.get("notify_count", 1)

            # 視覺邏輯：統一價格顏色 (漲為柔玫瑰紅、跌為翡翠綠、平盤為石板灰)
            price_color = "#f43f5e" if pct > 0 else ("#10b981" if pct < 0 else "#94a3b8")
            
            # 視覺邏輯：通知次數熱力顏色
            if count >= 5:
                count_color = "#f43f5e"  # 5次以上：柔紅
            elif 2 <= count <= 4:
                count_color = "#f97316"  # 2~4次：暖橘
            else:
                count_color = "#eab308"  # 1次：柔黃

            # 組裝單檔股票 UI 區塊 (強調餘白與資訊降噪)
            stock_row = {
                "type": "box", "layout": "vertical", "margin": "xl" if item_index > 0 else "none",
                "contents": [
                    # 🎯 第一橫排：股號股名 (天空藍連結) + 通知次數
                    {
                        "type": "box", "layout": "horizontal",
                        "contents": [
                            {
                                "type": "text", "text": f"{sid} {name}", "size": "md", "weight": "bold", 
                                "color": "#3b82f6", "decoration": "underline", "flex": 3,
                                "action": {
                                    "type": "uri", "label": "查看走勢", 
                                    "uri": f"https://www.nstock.tw/stock_info?stock_id={sid}"
                                }
                            },
                            {
                                "type": "text", "text": f"通知 {count} 次", "size": "xs", 
                                "color": count_color, "align": "end", "weight": "bold", "flex": 1
                            }
                        ]
                    },
                    
                    # 🎯 第二橫排：產業與細分族群
                    {"type": "text", "text": f"[{industry}] {sub_industry}", "size": "xs", "color": "#94a3b8", "margin": "sm"},
                    
                    # 🎯 第三橫排：現價與漲跌幅(完美合併無斷層)、量比(無粗體)、停損(無粗體)
                    {
                        "type": "box", "layout": "horizontal", "margin": "md",
                        "contents": [
                            {
                                "type": "text", "text": f"現價: {price} ({pct:+g}%)", "size": "sm", 
                                "color": price_color, "flex": 2
                            },
                            {"type": "text", "text": f"量比: {vol_ratio}x", "size": "sm", "color": "#d97706", "flex": 1},
                            {"type": "text", "text": f"停損: {stop_loss}", "size": "sm", "color": "#64748b", "flex": 1}
                        ]
                    }
                ]
            }
            body_contents.append(stock_row)
            
            # 分隔線 (超輕透的 #f1f5f9)
            if item_index < len(chunk) - 1:
                body_contents.append({"type": "separator", "margin": "xl", "color": "#f1f5f9"})

        # 將當前組裝好的分頁 (Bubble) 塞入輪播陣列 (Carousel Array) 中
        carousel_bubbles.append({
            "type": "bubble", "size": "giga",
            "header": header_box,
            "body": {"type": "box", "layout": "vertical", "paddingAll": "20px", "backgroundColor": "#ffffff", "contents": body_contents}
        })

    # ==========================================
    # 🎯 回傳最終的 Carousel 容器
    # ==========================================
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
