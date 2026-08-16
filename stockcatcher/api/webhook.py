# 檔案位置：api/webhook.py
 
import os
import re
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
   PushMessageRequest,  # 用於例外處理時的推播
   FlexMessage,
   TextMessage,
   FlexContainer
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent
from supabase import create_client, Client
from dotenv import load_dotenv
 
# 引入 Bibi Agent
from services.bibi_agent import ask_bibi_agent
# 💡 [蘇蘇新增] 引入動態 TIDE 共振引擎
from services.tide_service import get_real_tide_resonance
 
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
 
 # 💡 [蘇蘇新增] LIFF URL 環境變數，避免硬編碼
LIFF_TIDE_URL = os.getenv("LIFF_TIDE_URL", "https://liff.line.me/2009666448-Cqkm4xS4")
 
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
       # 1. 取得台灣時間的今日起訖點 (Asia/Taipei UTC+8)
       tw_tz = timezone(timedelta(hours=8))
       tw_now = datetime.now(tw_tz)
       
       # 產出 ISO 8601 格式的今日邊界
       start_of_day = datetime.combine(tw_now.date(), time.min, tzinfo=tw_tz).isoformat()
       end_of_day = datetime.combine(tw_now.date(), time.max, tzinfo=tw_tz).isoformat()
 
       # 2. 執行資料庫查詢：模糊比對 + 當日區間 + 最新優先
       response = supabase.table("tianji_signals") \
           .select("updated_at, data") \
           .eq("category", keyword) \
           .gte("updated_at", start_of_day) \
           .lte("updated_at", end_of_day) \
           .order("updated_at", desc=True) \
           .execute()
 
       records = response.data
       if not records:
           return [], "今日尚無資料"
 
       # 3. 效能優化：因為是降冪排序，第一筆絕對是最新時間
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
 
       # 4. O(N) 高效去重與聚合
       stock_map = {}
       for row in records:
           payload = row.get("data", {})
           if not isinstance(payload, dict):
               continue
               
           stock_id = payload.get("stock_id")
           if not stock_id:
               continue
 
           if stock_id not in stock_map:
               # 第一次遇到該股號 (因為降冪排序，此為最新狀態)
               stock_map[stock_id] = payload
               stock_map[stock_id]["notify_count"] = 1
           else:
               # 後續遇到舊紀錄，只累加通知次數
               stock_map[stock_id]["notify_count"] += 1
               
       aggregated_list = list(stock_map.values())
       
       # 5. 商業邏輯排序：通知次數 (遞減) -> 預估量比 (遞減)
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
 
def fetch_tide_cache() -> dict | None:
    """從 Supabase system_cache 讀取盤中大腦寫入的 TIDE 快取資料"""
    try:
        response = supabase.table("system_cache") \
            .select("cache_value") \
            .eq("cache_key", "tide_top_5") \
            .execute()
            
        if response.data and len(response.data) > 0:
            return response.data[0]["cache_value"]
        return None
    except Exception as e:
        print(f"❌ [TIDE 快取讀取錯誤] {e}")
        print(traceback.format_exc())
        return None
 
# ==========================================
# 💾 TIDE 資料調度層 (Cache-Aside Pattern)
# ==========================================
# ==========================================
# 💾 TIDE 資料調度層與 TTL 快取機制 (專業修正版)
# ==========================================
def get_tide_data_with_cache() -> list:
    """
    具備 60 秒 TTL 保護的盤中即時資料調度層。
    修正了快取污染問題，確保空狀態 (Empty State) 也能正確覆寫舊快取。
    """
    try:
        from datetime import datetime, timezone, timedelta
        tw_tz = timezone(timedelta(hours=8))
        
        # 1. 嘗試讀取快取與其更新時間
        cached_data, updated_at_str = fetch_tide_cache()
        
        # 2. 驗證快取是否過期 (TTL = 60 秒)
        is_cache_valid = False
        if cached_data is not None and updated_at_str:
            try:
                iso_time_str = str(updated_at_str).replace("Z", "+00:00")
                cache_time = datetime.fromisoformat(iso_time_str).astimezone(tw_tz)
                now_time = datetime.now(tw_tz)
                
                diff_seconds = (now_time - cache_time).total_seconds()
                if diff_seconds < 60:  # 60秒內視為新鮮
                    is_cache_valid = True
            except Exception as time_err:
                print(f"⚠️ [時間解析警告] 無法判斷快取新鮮度，強制重新運算: {time_err}")

        # 3. 路由決策
        if is_cache_valid:
            print(f"👉 [Cache Hit] 讀取 60 秒內的高速即時快取")
            return cached_data
            
        # 4. 快取未命中或已過期，啟動正式盤中即時引擎
        print("👉 [Cache Miss/Expired] 快取已過期，啟動資料庫即時重新運算...")
        # 這裡會去呼叫我們稍早加上了「時間結界」的引擎，因為今天沒開盤，會拿到 []
        real_data_list = get_real_tide_resonance(supabase, signals_table="tianji_signals")
        
        # 5. 🚨 關鍵修正：強制回寫快取 (Force Upsert)
        # 移除 if real_data_list: 的限制，即使是 [] 空陣列，也要寫入資料庫洗掉舊資料！
        try:
            # 確保寫入的資料型態是 list，若是 None 則強制轉為空陣列
            safe_data = real_data_list if isinstance(real_data_list, list) else []
            
            supabase.table("system_cache").upsert({
                "cache_key": "tide_top_5",
                "cache_value": safe_data
            }).execute()
            print(f"👉 [Cache Update] 最新盤中狀態 (包含空值狀態) 已刷新至系統快取")
        except Exception as cache_err:
            print(f"⚠️ [Cache Update Warning] 快取回寫失敗: {cache_err}")

        return safe_data
        
    except Exception as e:
        print(f"❌ [TIDE 調度層錯誤] {e}")
        return []


# ==========================================
# 🧠 意圖解析層 (Intent Parsing Layer)
# ==========================================
def parse_user_intent(raw_msg: str) -> str:
   """將非結構化的自然語言收斂為標準的系統指令路由"""
   clean_msg = raw_msg.strip().replace(" ", "").lower()
 
   warrant_keywords = ["權證主力", "權證發動", "權證介入"]
   volume_3k_keywords = ["3k突破", "量能異常", "3k量能", "3k發動"]
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
   """動態組裝 LINE Flex Message (具備強制定型與容量限制防護)"""
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
 
   # 🛡️ 容量防護：降低 MAX_BUBBLES 避免超過 LINE 的 50KB 限制
   ITEMS_PER_PAGE = 5  
   MAX_BUBBLES = 8    
   
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
           
           # 🛡️ 髒資料防護：強制轉型，防止伺服器因型別異常而崩潰
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
                           {"type": "text", "text": f"通知 {count} 次", "size": "xs", "color": count_color, "align": "end", "flex": 1}
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


# 💡 [蘇蘇更新] TIDE 專屬卡片生成器 (無印風格 Muji Style)
def build_tide_flex(tide_data_list: list) -> FlexContainer:
    """動態組裝 TIDE 族群共振卡片 (專業交易終端風格 Pro-Dashboard)"""
    
    # 取得當前台灣時間，增加卡片的即時感與專業度
    from datetime import datetime, timezone, timedelta
    tw_tz = timezone(timedelta(hours=8))
    current_time = datetime.now(tw_tz).strftime("%H:%M:%S")

    # ---------------------------------------------------------
    # 1. 異常防呆處理 (Empty State)
    # ---------------------------------------------------------
    if not tide_data_list:
        return FlexContainer.from_dict({
            "type": "bubble", "size": "mega",
            "styles": {"body": {"backgroundColor": "#0F172A"}}, # 深色背景
            "body": {
                "type": "box", "layout": "vertical", "paddingAll": "24px",
                "contents": [
                    {"type": "text", "text": "⚠️ 盤中監控系統", "color": "#F87171", "weight": "bold", "size": "sm"},
                    {"type": "text", "text": "今日尚未偵測到強勢共振族群", "color": "#94A3B8", "margin": "md", "size": "xs"}
                ]
            }
        })

    # ---------------------------------------------------------
    # 2. 構建 Top 1 榜首專屬高光卡片 (Hero Section)
    # ---------------------------------------------------------
    top1 = tide_data_list[0]
    body_contents = [
        {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#1E293B", # 較淺的深色突顯區塊
            "paddingAll": "16px",
            "cornerRadius": "md",
            "contents": [
                {
                    "type": "text", 
                    "text": "👑 本日最強共振", 
                    "color": "#F59E0B", # 專業橘金色
                    "size": "xs", 
                    "weight": "bold"
                },
                {
                    "type": "box", 
                    "layout": "horizontal", 
                    "marginTop": "sm",
                    "contents": [
                        {
                            "type": "text", 
                            "text": str(top1.get('cluster_name', '未知')), 
                            "color": "#FFFFFF", 
                            "size": "xl", 
                            "weight": "bold", 
                            "flex": 3,
                            "wrap": True
                        },
                        {
                            "type": "text", 
                            "text": f"🔥 {top1.get('heat_score', 0)}", 
                            "color": "#EF4444", # 強勢紅
                            "size": "xl", 
                            "weight": "bold", 
                            "align": "end", 
                            "flex": 1
                        }
                    ]
                }
            ]
        }
    ]

    # ---------------------------------------------------------
    # 3. 構建 Top 2 ~ 5 追蹤清單 (List Section)
    # ---------------------------------------------------------
    if len(tide_data_list) > 1:
        list_contents = []
        for idx in range(1, len(tide_data_list)):
            item = tide_data_list[idx]
            score = item.get('heat_score', 0)
            
            # 依據分數給予不同層級的顏色標籤
            score_color = "#F97316" if score >= 5 else "#38BDF8" 

            list_contents.append({
                "type": "box", 
                "layout": "horizontal", 
                "contents": [
                    {
                        "type": "text", 
                        "text": f"{idx + 1}. {item.get('cluster_name', '未知')}", 
                        "size": "sm", 
                        "color": "#E2E8F0", 
                        "weight": "bold", 
                        "flex": 3
                    },
                    {
                        "type": "text", 
                        "text": f"熱度 {score}", 
                        "size": "xs", 
                        "color": score_color, 
                        "align": "end", 
                        "weight": "bold", 
                        "flex": 1
                    }
                ]
            })
            
            # 加上科技感的深色分隔線 (最後一筆不加)
            if idx < len(tide_data_list) - 1:
                list_contents.append({"type": "separator", "margin": "md", "color": "#334155"})
                
        body_contents.append({
            "type": "box", 
            "layout": "vertical", 
            "margin": "lg", 
            "paddingAll": "8px",
            "contents": list_contents
        })

    # ---------------------------------------------------------
    # 4. 組裝完整 Flex Message JSON
    # ---------------------------------------------------------
    flex_dict = {
        "type": "bubble",
        "size": "mega",
        "styles": {
            "body": {"backgroundColor": "#0F172A"} # 極深藍灰 (Slate 900)
        },
        "header": {
            "type": "box",
            "layout": "vertical",
            "paddingAll": "20px",
            "paddingBottom": "10px",
            "backgroundColor": "#0F172A",
            "contents": [
                {
                    "type": "box",
                    "layout": "horizontal",
                    "contents": [
                        {
                            "type": "text",
                            "text": "TIDE 資金共振天機圖",
                            "weight": "bold",
                            "color": "#38BDF8", # 科技藍
                            "size": "lg",
                            "flex": 4
                        },
                        {
                            "type": "text",
                            "text": "🟢 即時",
                            "color": "#10B981", # 運作中綠色
                            "size": "xs",
                            "weight": "bold",
                            "align": "end",
                            "flex": 1
                        }
                    ]
                },
                {
                    "type": "text",
                    "text": f"資料更新時間: {current_time}",
                    "size": "xxs",
                    "color": "#64748B",
                    "margin": "sm"
                }
            ]
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "paddingAll": "20px",
            "paddingTop": "10px",
            "contents": body_contents
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "paddingAll": "20px",
            "paddingTop": "10px",
            "backgroundColor": "#0F172A",
            "contents": [
                {
                    "type": "button",
                    "action": {
                        "type": "uri",
                        "label": "📊 開啟深度儀表板",
                        "uri": LIFF_TIDE_URL # 從全域環境變數讀取
                    },
                    "style": "primary",
                    "color": "#2563EB", # 專業操作按鈕藍
                    "height": "sm"
                }
            ]
        }
    }
    return FlexContainer.from_dict(flex_dict)

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
       # 🛡️ 全域防護：捕捉頂層錯誤並印出詳細堆疊，防止系統悄悄掛點
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
   # 💡 捷徑指令通道：#分析 股名 (跳過第一層 LLM，節省 API 額度)
   match_fast_cmd = re.match(r'(?i)^#分析\s*(.+)?', user_msg)
   
   # 💡 自然語言通道：[Hi] [，] 比鼻 [問題]
   match_natural = re.match(r'(?i)^(?:hi\s*[,，]?\s*)?比鼻', user_msg)
 
   # ------------------------------------------
   # 處理路徑 A: 快速指令 (#分析)
   # ------------------------------------------
   if match_fast_cmd:
       query = match_fast_cmd.group(1)
       if not query:
           # 防呆：如果只輸入 "#分析" 卻沒有給股名
           ai_reply = "請在 #分析 後面加上股票名稱或代號喔！（例如：#分析 2330台積電）"
       else:
           # 靜態注入個股意圖，呼叫 AI Agent
           query = query.strip()
           ai_reply = ask_bibi_agent(query, force_intent="INTENT_STOCK_FUNDAMENTAL")
           
       # 統一回覆文字訊息並結束
       with ApiClient(configuration) as api_client:
           line_bot_api = MessagingApi(api_client)
           line_bot_api.reply_message(
               ReplyMessageRequest(
                   reply_token=event.reply_token,
                   messages=[TextMessage(text=ai_reply)]
               )
           )
       return
 
   # ------------------------------------------
   # 處理路徑 B: 自然對話 (呼叫比鼻)
   # ------------------------------------------
   elif match_natural:
       # 安全切下 "比鼻" 後面的真實提問
       query = user_msg[match_natural.end():].strip()
       
       # 過濾緊接在 "比鼻" 後方的全形/半形逗號
       if query.startswith("，") or query.startswith(","):
           query = query[1:].strip()
           
       # 🛡️ 零成本防呆保護：只叫名字，絕對不呼叫 Gemini API
       if not query:
           static_guide = (
               "你好！我是專屬 AI 交易員比鼻 🤖\n\n"
               "請告訴我想分析哪一檔股票或市場資訊，例如：\n"
               "👉 比鼻，請分析 2330 台積電\n"
               "👉 比鼻，今天大盤資金流向如何？\n"
               "👉 #分析 6568宏觀"
           )
           with ApiClient(configuration) as api_client:
               line_bot_api = MessagingApi(api_client)
               line_bot_api.reply_message(
                   ReplyMessageRequest(
                       reply_token=event.reply_token,
                       messages=[TextMessage(text=static_guide)]
                   )
               )
           return
 
       # 有具體問題，走正常的雙腦解析流程
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
       signals, update_time = fetch_and_aggregate_signals("warrant_3k")
       reply_flex = build_strategy_list_flex("🎫 權證主力發動", signals, update_time)
       
   elif action_intent == "INTENT_VOLUME_3K":
       signals, update_time = fetch_and_aggregate_signals("volume_3k")
       reply_flex = build_strategy_list_flex("🔥 3K 量能異常", signals, update_time)
       
   elif action_intent == "INTENT_TIDE_HEATMAP":
        print("👉 [DEBUG] 觸發 TIDE 查詢...")
        try:
            # 💡 透過調度層取得資料 (自動處理 Cache 與即時運算)
            tide_data_list = get_tide_data_with_cache()
            reply_flex = build_tide_flex(tide_data_list)
        except Exception as e:
            print(f"❌ [TIDE 查詢錯誤] {e}")
            import traceback
            print(traceback.format_exc())
            reply_flex = build_tide_flex([])  # 發生錯誤時回傳空陣列防呆
       
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
           print(f"❌ [LINE API 發送失敗] Flex 格式錯誤或容量過大: {e}")
           print(traceback.format_exc())
           
           # 🛡️ 降級防護：若 Reply Token 耗盡，改用 Push Message 發送緊急提示
           try:
               user_id = getattr(event.source, "user_id", None)
               if user_id:
                   with ApiClient(configuration) as api_client:
                       line_bot_api = MessagingApi(api_client)
                       line_bot_api.push_message(
                           PushMessageRequest(
                               to=user_id,
                               messages=[TextMessage(text="抱歉，由於符合條件的股票過多或發生非預期錯誤，無法顯示卡片。工程師已介入處理中！")]
                           )
                       )
           except Exception as push_err:
               print(f"❌ [降級 Push 發送失敗] {push_err}")
