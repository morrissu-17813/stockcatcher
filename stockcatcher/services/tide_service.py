import os
import json
# 💡 [蘇蘇提醒] 必須確保匯入處理時間的相關套件
from datetime import datetime, timezone, timedelta, time
from collections import Counter
from typing import List, Dict

def get_real_tide_resonance(supabase_client, signals_table: str = "tianji_signals") -> List[Dict]:
    """
    動態計算 TIDE 族群共振熱度核心引擎。
    包含嚴謹的「台灣時間 (UTC+8) 當日邊界」過濾，確保資料 100% 為盤中即時。
    """
    try:
        print("👉 [TIDE Service] 開始從資料庫撈取今日發動訊號...")
        
        # ==========================================
        # Step 1: 取得精確的台灣時間 (UTC+8) 當日邊界
        # ==========================================
        tw_tz = timezone(timedelta(hours=8))
        tw_now = datetime.now(tw_tz)
        
        # 產出 ISO 8601 格式的今日 00:00:00 與 23:59:59
        start_of_day = datetime.combine(tw_now.date(), time.min, tzinfo=tw_tz).isoformat()
        end_of_day = datetime.combine(tw_now.date(), time.max, tzinfo=tw_tz).isoformat()

        # ==========================================
        # Step 2: 執行帶有時間結界的嚴謹查詢
        # ==========================================
        response = supabase_client.table(signals_table) \
            .select("category, data, updated_at") \
            .in_("category", ["volume_3k", "warrant_3k"]) \
            .gte("updated_at", start_of_day) \
            .lte("updated_at", end_of_day) \
            .execute()
            
        # 若今日盤中尚無資料，提早結束並回傳空陣列
        if not response.data:
            print("👉 [TIDE Service] 今日盤中尚無符合條件的訊號資料。")
            return []

        # ==========================================
        # Step 3: 解析 JSON 並提取唯一的股票代號 (動態型別防呆)
        # ==========================================
        signal_stocks = set()
        for row in response.data:
            raw_data = row.get("data", {})
            
            # 處理字串或已解析的字典型別
            if isinstance(raw_data, str):
                try:
                    data_json = json.loads(raw_data)
                except json.JSONDecodeError:
                    continue
            elif isinstance(raw_data, dict):
                data_json = raw_data
            else:
                continue

            stock_id = data_json.get("stock_id")
            if stock_id:
                signal_stocks.add(str(stock_id))
        
        if not signal_stocks:
            return []

        # ==========================================
        # Step 4: 核心查詢 - 透過 Inner Join 取得族群概念
        # ==========================================
        concept_response = supabase_client.table("theme_stocks") \
            .select("symbol, themes(concept_name)") \
            .in_("symbol", list(signal_stocks)) \
            .execute()
        
        # ==========================================
        # Step 5: 統計熱度並回傳 Top 5
        # ==========================================
        cluster_names = []
        for row in concept_response.data:
            theme_info = row.get("themes")
            if theme_info and isinstance(theme_info, dict):
                concept_name = theme_info.get("concept_name")
                if concept_name:
                    cluster_names.append(concept_name)
        
        # 利用 Counter 計算共振分數
        top_5 = Counter(cluster_names).most_common(5)
        
        # 轉換為前端 Flex Message 所需的資料結構
        tide_data_list = [
            {"cluster_name": name, "heat_score": score} 
            for name, score in top_5
        ]
        
        print(f"✅ [TIDE Service] 盤中運算完成，今日 Top 5 族群: {tide_data_list}")
        return tide_data_list

    except Exception as e:
        print(f"❌ [TIDE Service Error] 系統發生致命錯誤: {str(e)}")
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