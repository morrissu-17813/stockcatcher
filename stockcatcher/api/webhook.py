# 檔案位置：api/webhook.py
 
import os
import re
import json
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
   FlexContainer,
   ShowLoadingAnimationRequest  # 💡 蘇蘇新增：用於顯示「思考中...」動畫
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent
from supabase import create_client, Client
from dotenv import load_dotenv
from fastapi.middleware.cors import CORSMiddleware
 
# 引入 Bibi Agent
from services.bibi_agent import ask_bibi_agent
# 引入動態 TIDE 共振引擎
from services.tide_service import get_real_tide_resonance
 
# 載入環境變數
load_dotenv()
 
app = FastAPI()
 
# 🛡️ 企業級 CORS 安全設定
app.add_middleware(
   CORSMiddleware,
   # 🚨 嚴格限制：只允許 Vercel 前端正式網址與本地開發環境發起請求
   allow_origins=[
       "https://tide-dashboard-ebon.vercel.app",
       "http://localhost:5173"  
   ],
   allow_credentials=True,
   allow_methods=["GET", "POST", "OPTIONS"],
   allow_headers=["*"],
)
 
# ==========================================
# ⚙️ 環境變數與安全憑證配置
# ==========================================
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET", "")
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
 
# LIFF URL 環境變數，避免硬編碼
LIFF_TIDE_URL = "https://tide-dashboard-ebon.vercel.app"
 
# 初始化 LINE API 與 Webhook Handler
configuration = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)
 
# 初始化 Supabase 客戶端
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def get_now_tw():
    """取得台灣時間 (UTC+8)"""
    return datetime.now(timezone(timedelta(hours=8))) 
# ==========================================
# 💾 資料庫讀取與聚合層 (Data Access & Aggregation)
# ==========================================
def fetch_and_aggregate_signals(keyword: str) -> tuple[list, str]:
   """
   從 Supabase 獲取單行單標的 (Append-only) 訊號，並進行去重與聚合。
   使用 ilike 進行關鍵字模糊比對，精準夾出台灣時間今日的全日區間資料。
   """
   try:
       tw_tz = timezone(timedelta(hours=8))
       tw_now = datetime.now(tw_tz)
       
       start_of_day = datetime.combine(tw_now.date(), time.min, tzinfo=tw_tz).isoformat()
       end_of_day = datetime.combine(tw_now.date(), time.max, tzinfo=tw_tz).isoformat()
 
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
 
       stock_map = {}
       for row in records:
           payload = row.get("data", {})
           if not isinstance(payload, dict):
               continue
               
           stock_id = payload.get("stock_id")
           if not stock_id:
               continue
 
           if stock_id not in stock_map:
               stock_map[stock_id] = payload
               stock_map[stock_id]["notify_count"] = 1
           else:
               stock_map[stock_id]["notify_count"] += 1
               
       aggregated_list = list(stock_map.values())
       
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
 
def fetch_tide_cache() -> tuple:
   """
   從 Supabase 讀取 TIDE 快取，並同時回傳「資料內容」與「最後更新時間」。
   回傳格式: (cache_value, updated_at_str)
   """
   try:
       response = supabase.table("system_cache") \
           .select("cache_value, updated_at") \
           .eq("cache_key", "tide_top_5") \
           .execute()
           
       if response.data and len(response.data) > 0:
           return response.data[0].get("cache_value"), response.data[0].get("updated_at")
           
       return None, None
       
   except Exception as e:
       print(f"❌ [TIDE 快取讀取錯誤] {e}")
       print(traceback.format_exc())
       return None, None
 
# ==========================================
# 💾 TIDE 資料調度層與 TTL 快取機制
# ==========================================
def get_tide_data_with_cache() -> list:
   """具備 60 秒 TTL 保護的盤中即時資料調度層。"""
   try:
       tw_tz = timezone(timedelta(hours=8))
       
       cached_data, updated_at_str = fetch_tide_cache()
       
       is_cache_valid = False
       if cached_data is not None and updated_at_str:
           try:
               iso_time_str = str(updated_at_str).replace("Z", "+00:00")
               cache_time = datetime.fromisoformat(iso_time_str).astimezone(tw_tz)
               now_time = datetime.now(tw_tz)
               
               diff_seconds = (now_time - cache_time).total_seconds()
               if diff_seconds < 60:
                   is_cache_valid = True
           except Exception as time_err:
               print(f"⚠️ [時間解析警告] 無法判斷快取新鮮度，強制重新運算: {time_err}")
 
       if is_cache_valid:
           print(f"👉 [Cache Hit] 讀取 60 秒內的高速即時快取")
           return cached_data
           
       print("👉 [Cache Miss/Expired] 快取已過期，啟動資料庫即時重新運算...")
       real_data_list = get_real_tide_resonance(supabase, signals_table="tianji_signals")
       
       try:
           safe_data = real_data_list if isinstance(real_data_list, list) else []
           supabase.table("system_cache").upsert({
               "cache_key": "tide_top_5",
               "cache_value": safe_data
           }).execute()
           print(f"👉 [Cache Update] 最新盤中狀態已刷新至系統快取")
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
   # 🎯 [新增] SMC 網格查詢關鍵字
   smc_keywords = ["smc金蛋蛋", "金蛋蛋網格"]
 
   if any(k in clean_msg for k in warrant_keywords): return "INTENT_WARRANT_3K"
   if any(k in clean_msg for k in volume_3k_keywords): return "INTENT_VOLUME_3K"
   if any(k in clean_msg for k in tide_keywords): return "INTENT_TIDE_HEATMAP"
   if any(k in clean_msg for k in dashboard_keywords): return "INTENT_DASHBOARD"
   # 🚨 [修正 2] 補上缺失的路由判斷！這行才是真正啟動金蛋蛋查詢的鑰匙
   if any(k in clean_msg for k in smc_keywords): return "INTENT_SMC_GRID"  
     
   return "INTENT_UNKNOWN"
 
# ==========================================
# 🎨 視覺渲染層 (Presentation Layer)
# ==========================================
def build_strategy_list_flex(title: str, signals: list, update_time: str) -> FlexContainer:
   """動態組裝 LINE Flex Message"""
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
           
           try:
               price = float(s.get("price", 0.0) or 0.0)
               pct = float(s.get("pct", 0.0) or 0.0)
               vol_ratio = float(s.get("vol_ratio", 0.0) or 0.0)
               stop_loss = float(s.get("stop_loss", 0.0) or 0.0)
               count = int(s.get("notify_count", 1) or 1)
           except (ValueError, TypeError):
               price, pct, vol_ratio, stop_loss, count = 0.0, 0.0, 0.0, 0.0, 1
 
           price_color = "#f43f5e" if pct > 0 else ("#10b981" if pct < 0 else "#94a3b8")
           
           if count >= 5: count_color = "#f43f5e"  
           elif 2 <= count <= 4: count_color = "#f97316"  
           else: count_color = "#eab308"  
 
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
 
def build_tide_flex(tide_data_list: list) -> FlexContainer:
   """動態組裝 TIDE 族群共振卡片"""
   tw_tz = timezone(timedelta(hours=8))
   current_time = datetime.now(tw_tz).strftime("%H:%M:%S")
 
   if not tide_data_list:
       return FlexContainer.from_dict({
           "type": "bubble", "size": "mega",
           "styles": {"body": {"backgroundColor": "#0F172A"}},
           "body": {
               "type": "box", "layout": "vertical", "paddingAll": "24px",
               "contents": [
                   {"type": "text", "text": "⚠️ 盤中監控系統", "color": "#F87171", "weight": "bold", "size": "sm"},
                   {"type": "text", "text": "今日尚未偵測到強勢共振族群", "color": "#94A3B8", "margin": "md", "size": "xs"}
               ]
           }
       })
 
   top1 = tide_data_list[0]
   body_contents = [
       {
           "type": "box",
           "layout": "vertical",
           "backgroundColor": "#1E293B",
           "paddingAll": "16px",
           "cornerRadius": "md",
           "contents": [
               {
                   "type": "text",
                   "text": "👑 本日最強共振",
                   "color": "#F59E0B",
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
                           "color": "#EF4444",
                           "size": "xl",
                           "weight": "bold",
                           "align": "end",
                           "flex": 1
                       }
                   ]
               },
               {
                   "type": "text",
                   "text": f"發動標的：{top1.get('representative_stocks', '')}",
                   "color": "#94A3B8",
                   "size": "xs",
                   "marginTop": "md",
                   "wrap": True
               }
           ]
       }
   ]
 
   if len(tide_data_list) > 1:
       list_contents = []
       for idx in range(1, len(tide_data_list)):
           item = tide_data_list[idx]
           score = item.get('heat_score', 0)
           score_color = "#F97316" if score >= 5 else "#38BDF8"
 
           list_contents.append({
               "type": "box",
               "layout": "vertical",
               "spacing": "xs",
               "contents": [
                   {
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
                   },
                   {
                       "type": "text",
                       "text": item.get('representative_stocks', ''),
                       "color": "#64748B",
                       "size": "xxs",
                       "wrap": True
                   }
               ]
           })
           
           if idx < len(tide_data_list) - 1:
               list_contents.append({"type": "separator", "margin": "md", "color": "#334155"})
               
       body_contents.append({
           "type": "box",
           "layout": "vertical",
           "margin": "lg",
           "paddingAll": "8px",
           "contents": list_contents
       })
 
   flex_dict = {
       "type": "bubble",
       "size": "mega",
       "styles": {"body": {"backgroundColor": "#0F172A"}},
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
                           "color": "#38BDF8",
                           "size": "lg",
                           "flex": 4
                       },
                       {
                           "type": "text",
                           "text": "🟢 即時",
                           "color": "#10B981",
                           "size": "xs",
                           "weight": "bold",
                           "align": "end",
                           "flex": 1
                       }
                   ]
               },
               {"type": "text", "text": f"資料更新時間: {current_time}", "size": "xxs", "color": "#64748B", "margin": "sm"}
           ]
       },
       "body": {
           "type": "box", "layout": "vertical", "paddingAll": "20px", "paddingTop": "10px", "contents": body_contents
       },
       "footer": {
           "type": "box", "layout": "vertical", "paddingAll": "20px", "paddingTop": "10px", "backgroundColor": "#0F172A",
           "contents": [
               {
                   "type": "button",
                   "action": {
                       "type": "uri",
                       "label": "📊 開啟深度儀表板",
                       "uri": LIFF_TIDE_URL
                   },
                   "style": "primary",
                   "color": "#2563EB",
                   "height": "sm"
               }
           ]
       }
   }
   return FlexContainer.from_dict(flex_dict)

def generate_muji_style_smc_flex(records: list, date_str: str) -> FlexContainer:
    """
    [展示層] 將 DB 撈出的網格資料，轉換為 LINE Flex Message (無印極簡風 / Carousel)
    🛡️ 效能優化：精準控制在 5 頁 x 12 筆 = 60 筆，總 JSON 體積約 42KB，完美閃避 LINE 50KB 物理上限。
    """
    if not records:
        return FlexContainer.from_dict({
            "type": "bubble", "size": "mega",
            "body": {
                "type": "box", "layout": "vertical", "paddingAll": "24px",
                "contents": [
                    {"type": "text", "text": f"📭 {date_str} 尚無有效的 SMC 網格資料。", "color": "#94a3b8", "align": "center"}
                ]
            }
        })

    # 🔻 架構師精算：每頁 12 筆，既不會讓氣泡太高，也能最大化利用 50KB 空間
    CHUNK_SIZE = 12  
    bubbles = []

    # 無印風配色學
    muji_bg = "#F9F9F6"       
    muji_text_main = "#333333" 
    muji_text_sub = "#888888"  
    muji_border = "#E5E5E5"    

    for i in range(0, len(records), CHUNK_SIZE):
        chunk = records[i:i + CHUNK_SIZE]
        
        box_contents = [
            {
                "type": "text",
                "text": f"SMC 網格 ． {date_str} (頁{i//CHUNK_SIZE + 1})",
                "weight": "bold",
                "size": "sm",
                "color": muji_text_main
            },
            {"type": "separator", "margin": "md", "color": muji_border},
            {
                "type": "box",
                "layout": "horizontal",
                "margin": "md",
                "contents": [
                    {"type": "text", "text": "標的", "size": "xxs", "color": muji_text_sub, "weight": "bold", "flex": 3},
                    {"type": "text", "text": "MH-H", "size": "xxs", "color": muji_text_sub, "align": "end", "flex": 2},
                    {"type": "text", "text": "E-LL", "size": "xxs", "color": muji_text_sub, "align": "end", "flex": 2},
                    {"type": "text", "text": "PT", "size": "xxs", "color": muji_text_sub, "align": "end", "flex": 2},
                    {"type": "text", "text": "E-HH", "size": "xxs", "color": muji_text_sub, "align": "end", "flex": 2},
                    {"type": "text", "text": "MH-L", "size": "xxs", "color": muji_text_sub, "align": "end", "flex": 2}
                ]
            },
            {"type": "separator", "margin": "sm", "color": muji_border}
        ]

        # 迭代寫入每一列股票資料
        for row in chunk:
            # 🛡️ 空字串防護
            stock_id = str(row.get('stock_id') or '0000').strip()
            stock_name = str(row.get('stock_name') or '未知')[:3].strip()
            short_name = f"{stock_id} {stock_name}".strip() or "-"
            
            def safe_num(val):
                s = str(val).strip() if val is not None else "0"
                return s if s else "0"

            row_box = {
                "type": "box",
                "layout": "horizontal",
                "margin": "sm",
                "contents": [
                    {"type": "text", "text": short_name, "size": "xxs", "color": muji_text_main, "weight": "bold", "flex": 3},
                    {"type": "text", "text": safe_num(row.get('mh_h')), "size": "xxs", "color": muji_text_main, "align": "end", "flex": 2},
                    {"type": "text", "text": safe_num(row.get('egg_ll')), "size": "xxs", "color": muji_text_main, "align": "end", "flex": 2},
                    {"type": "text", "text": safe_num(row.get('pt')), "size": "xxs", "color": muji_text_main, "align": "end", "flex": 2},
                    {"type": "text", "text": safe_num(row.get('egg_hh')), "size": "xxs", "color": muji_text_main, "align": "end", "flex": 2},
                    {"type": "text", "text": safe_num(row.get('mh_l')), "size": "xxs", "color": muji_text_main, "align": "end", "flex": 2}
                ]
            }
            box_contents.append(row_box)

        bubble = {
            "type": "bubble",
            "size": "giga",  
            "styles": {"body": {"backgroundColor": muji_bg}},
            "body": {
                "type": "box",
                "layout": "vertical",
                "paddingAll": "15px",
                "contents": box_contents
            }
        }
        bubbles.append(bubble)

    # 🛡️ 企業級防護二：嚴格裁切至前 5 頁 (共 60 檔)，確保 JSON 不超過 50KB 上限
    if len(bubbles) > 5:
        bubbles = bubbles[:5]

    return FlexContainer.from_dict({
        "type": "carousel",
        "contents": bubbles
    })

# ==========================================
# 🎯 SMC 金蛋蛋：資料庫查詢與 Flex 封裝層
# ==========================================
def fetch_smc_grid_flex() -> FlexContainer:
    """
    從 DB 撈取最新 SMC 網格資料，並封裝成無印風 Flex Message。
    具備智慧日期探測，可自動降級至最近一個有效交易日。
    """
    if not supabase:
        return generate_muji_style_smc_flex([], get_now_tw().strftime('%Y-%m-%d'))

    try:
        # 1. 🛡️ 智慧探測：查詢資料庫中最新的一筆網格資料是哪一天
        latest_date_res = supabase.table("tianji_smc_grids") \
            .select("date") \
            .order("date", desc=True) \
            .limit(1) \
            .execute()

        if not latest_date_res.data:
            print("⚠️ [SMC 查詢] 資料庫中沒有任何網格紀錄。")
            return generate_muji_style_smc_flex([], get_now_tw().strftime('%Y-%m-%d'))
            
        # 取得資料庫中最新的交易日
        target_date = latest_date_res.data[0]['date']
        
        # 2. 撈取該「最新交易日」的所有網格快照
        response = supabase.table("tianji_smc_grids") \
            .select("*") \
            .eq("date", target_date) \
            .order("stock_id") \
            .execute()
            
        records = response.data
        print(f"✅ [SMC 查詢] 成功組裝 {len(records)} 檔網格卡片 (日期: {target_date})。")
        
        # 回傳組裝好的 FlexContainer 給控制器
        return generate_muji_style_smc_flex(records, target_date)
        
    except Exception as e:
        import traceback
        print(f"❌ [SMC 查詢錯誤] {e}")
        print(traceback.format_exc())
        return generate_muji_style_smc_flex([], get_now_tw().strftime('%Y-%m-%d'))

# ==========================================
# 🔄 輔助工具：顯示思考中動畫
# ==========================================
def show_bot_loading(user_id: str, seconds: int = 20):
   """
   呼叫 LINE 官方 API 顯示「思考中...」的對話動畫。
   具備容錯機制，即使發生網路異常也不影響核心業務邏輯。
   """
   if not user_id:
       return
   try:
       with ApiClient(configuration) as api_client:
           line_bot_api = MessagingApi(api_client)
           line_bot_api.show_loading_animation(
               ShowLoadingAnimationRequest(
                   chatId=user_id,
                   loadingSeconds=seconds
               )
           )
   except Exception as e:
       print(f"⚠️ [Loading Animation] 無法顯示思考中動畫: {e}")
 
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
       print(f"❌ [系統嚴重崩潰] {e}")
       print(traceback.format_exc())
       raise HTTPException(status_code=500, detail="Internal Server Error")
   return "OK"
 
# ==========================================
# 🌟 給 Vue 3 儀表板專用的 API 端點 (極速快取版)
# ==========================================
@app.get("/api/tide")
async def get_tide_dashboard_data():
   """
   提供給 Vue 3 前端儀表板的 API 端點。
   直接讀取 system_cache 中的 tide_top_5 快取，達到 O(1) 極速響應與零運算成本。
   保留了原有的 function 名稱確保系統相依性不被破壞。
   """
   try:
       # 1️⃣ 直接向 Supabase 查詢快取資料
       response = supabase.table("system_cache") \
           .select("cache_value, updated_at") \
           .eq("cache_key", "tide_top_5") \
           .execute()
 
       # 2️⃣ 處理快取不存在的邊界情況
       if not response.data:
           return {
               "status": "success",
               "message": "目前無盤中快取資料",
               "data": []
           }
 
       # 3️⃣ 解析資料
       cache_row = response.data[0]
       raw_value = cache_row.get("cache_value", "[]")
       
       # 安全地將 JSON 字串轉回 Python List/Dict
       tide_data = json.loads(raw_value) if isinstance(raw_value, str) else raw_value
 
       # 4️⃣ 回傳給前端
       return {
           "status": "success",
           "message": "盤中快取資料讀取成功",
           "data": tide_data,
           "updated_at": cache_row.get("updated_at")
       }
 
   except Exception as e:
       import traceback
       print(f"❌ [API Error] 讀取 system_cache 失敗: {str(e)}")
       print(traceback.format_exc())
       raise HTTPException(status_code=500, detail="伺服器內部錯誤，無法取得資金共振資料")
 
# ==========================================
# 🤖 LINE 訊息事件處理中樞 (Message Handler)
# ==========================================
@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
   """處理使用者對話與圖文選單按鈕觸發的查詢事件"""
   user_msg = event.message.text.strip()
   
   # 擷取使用者 ID，供 Loading Animation 使用
   user_id = getattr(event.source, "user_id", None)
 
   match_fast_cmd = re.match(r'(?i)^#分析\s*(.+)?', user_msg)
   match_natural = re.match(r'(?i)^(?:hi\s*[,，]?\s*)?比鼻', user_msg)
 
   # ------------------------------------------
   # 處理路徑 A: 快速指令 (#分析)
   # ------------------------------------------
   if match_fast_cmd:
       query = match_fast_cmd.group(1)
       if not query:
           ai_reply = "請在 #分析 後面加上股票名稱或代號喔！（例如：#分析 2330台積電）"
       else:
           query = query.strip()
           # 💡 [新增 UX] 在呼叫 LLM 前顯示思考動畫
           show_bot_loading(user_id=user_id, seconds=20)
           ai_reply = ask_bibi_agent(query, force_intent="INTENT_STOCK_FUNDAMENTAL")
           
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
       query = user_msg[match_natural.end():].strip()
       
       if query.startswith("，") or query.startswith(","):
           query = query[1:].strip()
           
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
 
       # 💡 [新增 UX] 在呼叫複雜的 AI 解析流程前顯示思考動畫
       show_bot_loading(user_id=user_id, seconds=30)
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
 
   # ------------------------------------------
   # 處理路徑 C: 圖文選單與制式意圖
   # ------------------------------------------
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
       # 💡 [新增 UX] 即使有快取，仍可顯示極短暫的載入動畫，提升科技感
       show_bot_loading(user_id=user_id, seconds=5)
       try:
           tide_data_list = get_tide_data_with_cache()
           reply_flex = build_tide_flex(tide_data_list)
       except Exception as e:
           print(f"❌ [TIDE 查詢錯誤] {e}")
           print(traceback.format_exc())
           reply_flex = build_tide_flex([])  
           
    # 🎯 [新增] SMC 金蛋蛋查詢邏輯
   elif action_intent == "INTENT_SMC_GRID":
        print("👉 [DEBUG] 觸發 SMC 金蛋蛋查詢...")
        show_bot_loading(user_id=user_id, seconds=5)
        # 呼叫強大的查詢與封裝引擎，直接取得 Flex 卡片
        reply_flex = fetch_smc_grid_flex()        

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
           
           try:
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
