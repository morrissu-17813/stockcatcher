import os
import json
from collections import Counter
from typing import List, Dict

def get_real_tide_resonance(supabase_client, signals_table: str = "signals") -> List[Dict]:
    """
    動態計算 TIDE 族群共振熱度核心引擎。
    
    運算流程：
    1. 從訊號表中，透過 category 撈取今日的 'volume_3k' 與 'warrant_3k' 訊號。
    2. 解析 data 欄位 (JSON字串)，萃取唯一的股票代號 (stock_id) 並去重。
    3. 利用 Foreign Key 關聯「個股對應表 (theme_stocks)」與「概念主題表 (themes)」。
    4. 統計族群出現的頻次（熱度），並回傳分數最高的前 5 名。
    """
    try:
        print("👉 [TIDE Service] 開始從資料庫撈取今日發動訊號...")
        
        # ---------------------------------------------------------
        # Step 1: 取得今日所有發動的股票代號
        # 🚨 註：預設表名為 signals，若你的表名不同，呼叫時可傳入 signals_table 參數
        # ---------------------------------------------------------
        response = supabase_client.table(signals_table) \
            .select("category, data") \
            .in_("category", ["volume_3k", "warrant_3k"]) \
            .execute()
            
        if not response.data:
            print("👉 [TIDE Service] 今日尚無符合條件的訊號資料。")
            return []

        # ---------------------------------------------------------
        # Step 2: 解析 JSON 並提取唯一的股票代號
        # ---------------------------------------------------------
        signal_stocks = set()
        for row in response.data:
            raw_data = row.get("data", {})
            
            # 💡 [蘇蘇優化] 動態型別防呆：
            # 若資料庫欄位為 Text，會拿到字串 (str)，需解析
            # 若資料庫欄位為 JSONB，Supabase 會自動轉為字典 (dict)，直接使用
            if isinstance(raw_data, str):
                try:
                    data_json = json.loads(raw_data)
                except json.JSONDecodeError:
                    print(f"⚠️ [TIDE Service] 發現無效的 JSON 字串，略過此筆資料。")
                    continue
            elif isinstance(raw_data, dict):
                data_json = raw_data
            else:
                print("⚠️ [TIDE Service] 資料格式未獲支援，略過此筆資料。")
                continue

            # 萃取股票代號並統一轉為字串去重
            stock_id = data_json.get("stock_id")
            if stock_id:
                signal_stocks.add(str(stock_id))
        
        if not signal_stocks:
            print("👉 [TIDE Service] 訊號中無有效的股票代號。")
            return []

        # ---------------------------------------------------------
        # Step 3: 核心查詢 - 透過 Inner Join 取得族群概念
        # ---------------------------------------------------------
        print(f"👉 [TIDE Service] 準備查詢 {len(signal_stocks)} 檔股票的族群概念...")
        concept_response = supabase_client.table("theme_stocks") \
            .select("symbol, themes(concept_name)") \
            .in_("symbol", list(signal_stocks)) \
            .execute()
        
        # ---------------------------------------------------------
        # Step 4: 統計熱度並回傳 Top 5
        # ---------------------------------------------------------
        cluster_names = []
        for row in concept_response.data:
            theme_info = row.get("themes")
            # 防呆機制：確保關聯資料存在且格式正確
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
        
        print(f"✅ [TIDE Service] 運算完成，Top 5 共振族群: {tide_data_list}")
        return tide_data_list

    except Exception as e:
        print(f"❌ [TIDE Service Error] 系統發生致命錯誤: {str(e)}")
        # 發生錯誤時回傳空陣列，避免引發 LINE 機器人崩潰
        return []

# ==========================================
# 🧪 本地端單元測試區塊 (僅在直接執行此檔案時觸發)
# ==========================================
if __name__ == "__main__":
    # 頂層追蹤點：用於確認直譯器是否有成功讀取到檔案的最新版本
    print("🚀 [系統測試] 成功讀取到 tide_service.py 檔案！準備啟動本地驗證...")
    
    try:
        from dotenv import load_dotenv
        from supabase import create_client, Client
        
        # 載入專案根目錄的 .env 檔案
        load_dotenv()
        
        # 安全讀取環境變數，絕對不硬編碼 (Hardcode) 敏感金鑰
        SUPABASE_URL = os.getenv("SUPABASE_URL")
        SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY") # 亦可使用 SUPABASE_ANON_KEY
        
        if not SUPABASE_URL or not SUPABASE_KEY:
            print("❌ [環境變數錯誤] 找不到 Supabase 憑證，請確認專案根目錄下的 .env 檔案已正確設定。")
        else:
            print("👉 [TEST] 正在初始化 Supabase 客戶端連線...")
            supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
            
            print("👉 [TEST] 開始執行 TIDE 共振運算引擎...")
           
            # 💡 修正：將真實資料表名稱 tianji_signals 傳入
            result = get_real_tide_resonance(supabase, signals_table="tianji_signals")
            
            print("\n✅ [TEST] 最終運算結果如下：")
            print(json.dumps(result, indent=2, ensure_ascii=False))
            
    except ImportError as e:
        print("❌ [套件缺失] 無法執行測試。請確認是否已安裝必要套件：")
        print("請在虛擬環境執行: pip install python-dotenv supabase")
        print(f"錯誤細節: {e}")