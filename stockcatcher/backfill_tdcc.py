import os
import time
import requests
import pandas as pd
from supabase import create_client, Client
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

# ==========================================
# ⚙️ 設定區
# ==========================================
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# FinMind API 端點
FINMIND_URL = "https://api.finmindtrade.com/api/v4/data"

def get_target_symbols() -> list:
    """從 Supabase 取得目前關注的概念股代號，縮小回補範圍以避開 API 限制"""
    res = supabase.table("theme_stocks").select("symbol").execute()
    return list(set(row["symbol"] for row in res.data))

def backfill_stock_history(symbol: str, start_date: str):
    """透過 FinMind 撈取單一個股歷史集保分佈"""
    params = {
        "dataset": "TaiwanStockHoldingSharesPer",
        "data_id": symbol,
        "start_date": start_date
    }
    
    try:
        res = requests.get(FINMIND_URL, params=params, timeout=10)
        res.raise_for_status()
        data = res.json()
        
        if data.get("msg") != "success" or not data.get("data"):
            return []
            
        df = pd.DataFrame(data["data"])
        
        # 轉換日期格式 (FinMind: 2026-08-28 -> Supabase: 20260828)
        df['date'] = df['date'].str.replace("-", "")
        
        records = []
        # 按日期分組計算 400 張與 1000 張大戶
        for date_val, group in df.groupby('date'):
            # Level 15: 千張以上, Level 12-15: 400張以上
            ratio_1000k = group[group['HoldingSharesLevel'] == '15']['percent'].sum()
            ratio_400k = group[group['HoldingSharesLevel'].isin(['12', '13', '14', '15'])]['percent'].sum()
            
            records.append({
                "date": date_val,
                "symbol": symbol,
                "ratio_1000k": round(float(ratio_1000k), 2),
                "ratio_400k": round(float(ratio_400k), 2)
            })
            
        return records
    except Exception as e:
        print(f"❌ 取得 {symbol} 失敗: {e}")
        return []

def main():
    print("🚀 啟動 TDCC 歷史資料回補程序 (過去 12 週)...")
    
    # 計算 12 週前的日期
    twelve_weeks_ago = (datetime.now() - timedelta(weeks=12)).strftime("%Y-%m-%d")
    
    target_symbols = get_target_symbols()
    print(f"📦 共鎖定 {len(target_symbols)} 檔主題概念股進行精準回補")
    
    for idx, symbol in enumerate(target_symbols):
        print(f"[{idx+1}/{len(target_symbols)}] 正在回補 {symbol} ...")
        
        records = backfill_stock_history(symbol, twelve_weeks_ago)
        
        if records:
            # 寫入 Supabase (使用 upsert 避免主鍵衝突)
            supabase.table("tdcc_history").upsert(records).execute()
            print(f"   ✅ 成功寫入 {len(records)} 期歷史資料")
            
        # 禮貌性延遲，避免觸發 FinMind 免費版每小時 300 次的 API 限制
        time.sleep(2)

    print("🎉 歷史資料回補完成！你的 LINE Bot 現在應該能正常運算差值了。")

if __name__ == "__main__":
    main()