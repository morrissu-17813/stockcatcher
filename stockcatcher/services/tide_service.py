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
 
       signal_stocks_map = {}
       for row in data_rows:
            raw_data = row.get("data", {})
            data_json = json.loads(raw_data) if isinstance(raw_data, str) else raw_data
            if not isinstance(data_json, dict): continue

            sid = data_json.get("stock_id")
            sname = data_json.get("stock_name", "")
            
            try: pct = float(data_json.get("pct", 0.0) or 0.0)
            except: pct = 0.0
            
            # 💡 提取量能比 (如果 JSON 內沒傳，預設給 1.0)
            try: vol_ratio = float(data_json.get("vol_ratio", 1.0) or 1.0)
            except: vol_ratio = 1.0

            if pct <= -3.0: continue # 剔除弱勢股

            if sid:
                # 🚨 改變結構：改為存入完整的 Detail Dict
                signal_stocks_map[str(sid)] = {
                    "sid": str(sid),
                    "name": str(sname).strip(),
                    "pct": pct,
                    "vol_ratio": vol_ratio
                }
        
       if not signal_stocks_map: return []

        # 查詢族群概念
       concept_response = supabase_client.table("theme_stocks").select("symbol, themes(concept_name)").in_("symbol", list(signal_stocks_map.keys())).execute()
       concept_to_stocks = defaultdict(list)
        
       for row in concept_response.data:
            theme_info = row.get("themes")
            sid = str(row.get("symbol"))
            stock_detail = signal_stocks_map.get(sid)

            if not theme_info or not stock_detail: continue

            if isinstance(theme_info, list):
                for t in theme_info:
                    c_name = t.get("concept_name")
                    if c_name and not any(s['sid'] == sid for s in concept_to_stocks[c_name]):
                        concept_to_stocks[c_name].append(stock_detail)
            elif isinstance(theme_info, dict):
                c_name = theme_info.get("concept_name")
                if c_name and not any(s['sid'] == sid for s in concept_to_stocks[c_name]):
                    concept_to_stocks[c_name].append(stock_detail)
        
        # 排序並產生最終 Payload
       cluster_counts = {name: len(stocks) for name, stocks in concept_to_stocks.items()}
       top_5 = Counter(cluster_counts).most_common(5)
        
       tide_data_list = []
       for name, score in top_5:
            # 將族群內的股票依據漲跌幅 (pct) 降冪排序
            stocks_list = sorted(concept_to_stocks[name], key=lambda x: x['pct'], reverse=True)
            
            # 計算該族群的平均資金量能比
            avg_vol_ratio = sum(s['vol_ratio'] for s in stocks_list) / len(stocks_list) if stocks_list else 1.0
            
            rep_stocks = [f"{s['sid']} {s['name']}" for s in stocks_list[:2]]
            
            tide_data_list.append({
                "cluster_name": name,
                "heat_score": score,
                "vol_ratio": round(avg_vol_ratio, 2),
                "representative_stocks": "、".join(rep_stocks),
                # 🚨 新增：供應給前端點擊後顯示的完整明細陣列
                "stocks_detail": stocks_list 
            })
            
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
