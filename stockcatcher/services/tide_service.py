import os
import json
# 💡 [蘇蘇提醒] 必須確保匯入處理時間的相關套件
from datetime import datetime, timezone, timedelta, time
from collections import Counter
from typing import List, Dict
def get_real_tide_resonance(supabase_client, signals_table: str = "tianji_signals") -> List[Dict]:
   """
   動態計算 TIDE 族群共振熱度核心引擎 (附帶領漲標的萃取)。
   """
   try:
       tw_tz = timezone(timedelta(hours=8))
       tw_now = datetime.now(tw_tz)
       start_of_day = datetime.combine(tw_now.date(), time.min, tzinfo=tw_tz).isoformat()
       end_of_day = datetime.combine(tw_now.date(), time.max, tzinfo=tw_tz).isoformat()
 
       # 1. 撈取今日盤中訊號
       response = supabase_client.table(signals_table) \
           .select("category, data, updated_at") \
           .in_("category", ["volume_3k", "warrant_3k"]) \
           .gte("updated_at", start_of_day) \
           .lte("updated_at", end_of_day) \
           .execute()
           
       if not response.data:
           return []
 
       # 2. 💡 [蘇蘇優化] 建立股票映射表 (stock_id -> stock_name)
       signal_stocks_map = {}
       for row in response.data:
           raw_data = row.get("data", {})
           if isinstance(raw_data, str):
               try: data_json = json.loads(raw_data)
               except: continue
           elif isinstance(raw_data, dict): data_json = raw_data
           else: continue
 
           sid = data_json.get("stock_id")
           sname = data_json.get("stock_name", "")
           if sid:
               # 去重並保留代號與名稱
               signal_stocks_map[str(sid)] = sname.strip()
       
       if not signal_stocks_map:
           return []
 
       # 3. 查詢族群概念
       concept_response = supabase_client.table("theme_stocks") \
           .select("symbol, themes(concept_name)") \
           .in_("symbol", list(signal_stocks_map.keys())) \
           .execute()
       
       # 4. 💡 [蘇蘇優化] 將發動的股票，反向歸類回對應的族群中
       concept_to_stocks = defaultdict(list)
       for row in concept_response.data:
           theme_info = row.get("themes")
           sid = str(row.get("symbol"))
           if theme_info and isinstance(theme_info, dict):
               concept_name = theme_info.get("concept_name")
               if concept_name:
                   # 組合出 "3363 上詮" 的格式
                   sname = signal_stocks_map.get(sid, "")
                   display_text = f"{sid} {sname}".strip()
                   if display_text not in concept_to_stocks[concept_name]:
                       concept_to_stocks[concept_name].append(display_text)
       
       # 5. 計算分數並排序
       cluster_counts = {name: len(stocks) for name, stocks in concept_to_stocks.items()}
       top_5 = Counter(cluster_counts).most_common(5)
       
       # 6. 萃取回傳結構：加入代表性標的 (最多取 2 檔)
       tide_data_list = []
       for name, score in top_5:
           # 取該族群前兩檔股票，用頓號連接
           rep_stocks = concept_to_stocks[name][:2]
           rep_stocks_str = "、".join(rep_stocks)
           
           tide_data_list.append({
               "cluster_name": name,
               "heat_score": score,
               "representative_stocks": rep_stocks_str  # 新增的領漲標的欄位
           })
           
       return tide_data_list
 
   except Exception as e:
       print(f"❌ [TIDE Service Error] {str(e)}")
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
