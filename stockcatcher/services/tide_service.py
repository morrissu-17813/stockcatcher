# 檔案位置：services/tide_service.py
import json
import datetime
from collections import Counter
from typing import List, Dict

def get_real_tide_resonance(supabase_client, table_name: str = "your_table_name_here") -> List[Dict]:
    """
    動態計算 TIDE 族群共振熱度。
    
    運算流程：
    1. 從單一資料表中，透過 category 撈取今日的 'volume_3k' 與 'warrant_3k' 訊號。
    2. 解析 data 欄位 (JSON字串)，萃取唯一的股票代號 (stock_id)。
    3. 關聯「概念股資料表」，轉換為族群標籤，並計算共振熱度 (Top 5)。
    """
    try:
        # ---------------------------------------------------------
        # Step 1: 獲取今日訊號股池 (Signal Pool)
        # ---------------------------------------------------------
        # 撈取今日兩種 category 的資料
        # 🚨 注意：這裡假設資料表只保留最新資料，或你可用 .gte('updated_at', today) 做日期過濾
        # 1. 取得今日所有發動的股票代號 (從 volume_3k 與 warrant_3k)
        # 這裡我們利用 category 篩選出今日兩大訊號池
        response = supabase_client.table("signals") \
            .select("category, data") \
            .in_("category", ["volume_3k", "warrant_3k"]) \
            .execute()
            
        if not response.data:
            print("👉 [TIDE] 今日尚無突破或權證主力訊號。")
            return []
            
        # ---------------------------------------------------------
        # Step 2: 解析 JSON，萃取發動的股票代號 (Set 去重)
        # ---------------------------------------------------------
        signal_stocks = set()
        for row in response.data:
            try:
                # 因為 data 欄位存的是 JSON 格式的字串，所以需要 loads
                raw_data = row.get("data", "{}")
                parsed_data = json.loads(raw_data)
                
                stock_id = parsed_data.get("stock_id")
                if stock_id:
                    signal_stocks.add(stock_id)
            except json.JSONDecodeError:
                print(f"❌ [TIDE] JSON 解析失敗，略過此筆資料: {row.get('id')}")
                continue
                
        if not signal_stocks:
            return []
            
        # ---------------------------------------------------------
        # Step 3: 映射概念族群 (Map Concept Clusters via Join)
        # ---------------------------------------------------------
        stock_list = list(signal_stocks)
        
        # 💡 利用 Supabase 的關聯查詢 (Join) 功能
        # 假設您的個股對應表名為 'theme_stocks'，概念主題表名為 'themes'
        # 語法 'themes(concept_name)' 會自動透過 Foreign Key 去對應的主表把名稱撈出來
        concept_response = supabase_client.table('theme_stocks') \
            .select('symbol, themes(concept_name)') \
            .in_('symbol', stock_list) \
            .execute()
            
        if not concept_response.data:
            print("👉 [TIDE] 訊號股池無法對應到任何已知的概念族群。")
            return []
            
        # ---------------------------------------------------------
        # Step 4: 聚合計算共振熱度 (Reduce & Calculate Heat Score)
        # ---------------------------------------------------------
        cluster_names = []
        
        for row in concept_response.data:
            # 由於使用了 Join，themes 欄位回傳的會是一個巢狀字典 (Nested Dict)
            # 資料結構範例: {"symbol": "2330", "themes": {"concept_name": "矽光子"}}
            theme_info = row.get('themes')
            
            # 安全取值防呆：確保有關聯到主題，且格式正確
            if theme_info and isinstance(theme_info, dict):
                concept_name = theme_info.get('concept_name')
                if concept_name:
                    cluster_names.append(concept_name)
        
        # 利用 Counter 自動統計每個族群出現的次數 (熱度)
        from collections import Counter
        cluster_counts = Counter(cluster_names)
        
        # 取得熱度最高的前 5 名
        top_5_clusters = cluster_counts.most_common(5)
        
        # 格式化為 Flex Message 需要的資料結構
        tide_data_list = [
            {"cluster_name": name, "heat_score": score}
            for name, score in top_5_clusters
        ]
        
        print(f"👉 [TIDE] 運算完成，今日 Top 5 共振族群: {tide_data_list}")
        return tide_data_list
        
    except Exception as e:
        print(f"❌ [DB Error] 計算 TIDE 共振資料發生致命錯誤: {str(e)}")
        # 發生非預期錯誤時，回傳空陣列，避免整個系統崩潰
        return []