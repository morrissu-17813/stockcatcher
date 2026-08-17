import os
import json
# 💡 [蘇蘇提醒] 必須確保匯入處理時間的相關套件
from datetime import datetime, timezone, timedelta, time
# 🚨 關鍵修正：必須從 collections 模組同時匯入 Counter 與 defaultdict
from collections import Counter, defaultdict
from typing import List, Dict

def get_real_tide_resonance(supabase_client, signals_table: str = "tianji_signals") -> List[Dict]:
   """
   動態計算 TIDE 族群共振熱度核心引擎
   (具備高容錯、弱勢股排除、以及「無資料時自動回溯至上一交易日」之優雅降級機制)
   """
   try:
       print("👉 [TIDE Service] 開始執行盤中熱度運算...")
       
       tw_tz = timezone(timedelta(hours=8))
       tw_now = datetime.now(tw_tz)
       
       # 預設查詢邊界為「今天」
       target_start = datetime.combine(tw_now.date(), time.min, tzinfo=tw_tz).isoformat()
       target_end = datetime.combine(tw_now.date(), time.max, tzinfo=tw_tz).isoformat()
 
       # ==========================================
       # 🟢 第一段查詢：嘗試撈取「目標日」的資料 (精準使用 updated_at)
       # ==========================================
       response = supabase_client.table(signals_table) \
           .select("category, data, updated_at") \
           .in_("category", ["volume_3k", "warrant_3k"]) \
           .gte("updated_at", target_start) \
           .lte("updated_at", target_end) \
           .execute()
           
       data_rows = response.data
 
       # ==========================================
       # 🟡 第二段查詢：智慧回溯機制 (Graceful Fallback)
       # ==========================================
       if not data_rows:
           print("⚠️ [TIDE Service] 今日尚無資料 (可能為假日或盤前)，啟動【尋找最近交易日】機制...")
           
           # 撈取資料庫中「最新的一筆」紀錄，藉此精準定位最後一個交易日
           latest_res = supabase_client.table(signals_table) \
               .select("updated_at") \
               .in_("category", ["volume_3k", "warrant_3k"]) \
               .order("updated_at", desc=True) \
               .limit(1) \
               .execute()
               
           if not latest_res.data:
               print("❌ [TIDE Service] 資料庫完全空無一物，無法回溯。")
               return []
               
           # 解析最後一筆資料的時間，並轉換為台灣時區的日期
           last_record_time_str = latest_res.data[0]['updated_at']
           # Supabase 預設回傳 UTC (結尾為 +00:00 或是 Z)，轉回台灣時區以確保日期正確
           iso_str_fixed = str(last_record_time_str).replace("Z", "+00:00")
           last_record_dt = datetime.fromisoformat(iso_str_fixed).astimezone(tw_tz)
           last_trade_date = last_record_dt.date()
           
           print(f"👉 [TIDE Service] 成功定位到最近交易日：{last_trade_date}，重新撈取該日資料...")
           
           # 重設時間結界為「上一個交易日」，進行二次撈取
           fallback_start = datetime.combine(last_trade_date, time.min, tzinfo=tw_tz).isoformat()
           fallback_end = datetime.combine(last_trade_date, time.max, tzinfo=tw_tz).isoformat()
           
           fallback_res = supabase_client.table(signals_table) \
               .select("category, data, updated_at") \
               .in_("category", ["volume_3k", "warrant_3k"]) \
               .gte("updated_at", fallback_start) \
               .lte("updated_at", fallback_end) \
               .execute()
               
           data_rows = fallback_res.data
 
       # 防呆：如果回溯了還是沒資料 (極端情況)
       if not data_rows:
           return []
 
       print(f"👉 [TIDE Service] 進入運算階段，共 {len(data_rows)} 筆有效訊號...")
 
       # ==========================================
       # 🎯 核心映射與過濾邏輯
       # ==========================================
       signal_stocks_map = {}
       for row in data_rows:
           raw_data = row.get("data", {})
           if isinstance(raw_data, str):
               try:
                   data_json = json.loads(raw_data)
               except json.JSONDecodeError:
                   continue
           elif isinstance(raw_data, dict):
               data_json = raw_data
           else:
               continue
 
           sid = data_json.get("stock_id")
           sname = data_json.get("stock_name", "")
           
           # 🛡️ 剔除弱勢股 (下跌超過 3%)
           try:
               pct = float(data_json.get("pct", 0.0) or 0.0)
           except (ValueError, TypeError):
               pct = 0.0
 
           if pct <= -3.0:
               continue
 
           if sid:
               signal_stocks_map[str(sid)] = str(sname).strip()
       
       if not signal_stocks_map:
           print("⚠️ [TIDE Service] 經過過濾後，無有效或強勢的股票代號。")
           return []
 
       # 查詢族群概念
       concept_response = supabase_client.table("theme_stocks") \
           .select("symbol, themes(concept_name)") \
           .in_("symbol", list(signal_stocks_map.keys())) \
           .execute()
       
       concept_to_stocks = defaultdict(list)
       
       for row in concept_response.data:
           theme_info = row.get("themes")
           sid = str(row.get("symbol"))
           sname = signal_stocks_map.get(sid, "")
           display_text = f"{sid} {sname}".strip()
 
           if not theme_info:
               continue
 
           # 兼容單一族群(dict)與多重族群(list)結構
           if isinstance(theme_info, list):
               for t in theme_info:
                   c_name = t.get("concept_name")
                   if c_name and display_text not in concept_to_stocks[c_name]:
                       concept_to_stocks[c_name].append(display_text)
           elif isinstance(theme_info, dict):
               c_name = theme_info.get("concept_name")
               if c_name and display_text not in concept_to_stocks[c_name]:
                   concept_to_stocks[c_name].append(display_text)
       
       # 計算分數並排序
       cluster_counts = {name: len(stocks) for name, stocks in concept_to_stocks.items()}
       top_5 = Counter(cluster_counts).most_common(5)
       
       tide_data_list = []
       for name, score in top_5:
           rep_stocks = concept_to_stocks[name][:2]
           rep_stocks_str = "、".join(rep_stocks)
           
           tide_data_list.append({
               "cluster_name": name,
               "heat_score": score,
               "representative_stocks": rep_stocks_str
           })
           
       print(f"✅ [TIDE Service] 運算完成！強勢族群：{[t['cluster_name'] for t in tide_data_list]}")
       return tide_data_list
 
   except Exception as e:
       import traceback
       print(f"❌ [TIDE Service Error] {str(e)}")
       print(traceback.format_exc())
       return []

# ==========================================
# 🧪 本地端單元測試區塊 
# ==========================================
if __name__ == "__main__":
    from dotenv import load_dotenv
    from supabase import create_client, Client
    
    load_dotenv()
    SUPABASE_URL = os.getenv("SUPABASE_URL")
    SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    
    if SUPABASE_URL and SUPABASE_KEY:
        print("👉 [TEST] 啟動嚴謹時間邊界測試...")
        supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
        result = get_real_tide_resonance(supabase, signals_table="tianji_signals")
        print("\n✅ [TEST] 最終運算結果如下：")
        print(json.dumps(result, indent=2, ensure_ascii=False))
