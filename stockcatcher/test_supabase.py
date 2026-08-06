import os
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
from supabase import create_client, Client

def test_supabase_connection():
    """
    [單元測試] 驗證 Supabase 環境變數載入與寫入權限
    """
    print("啟動 Supabase 連線測試...")
    
    # 1. 載入 .env 檔案
    load_dotenv()
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

    if not url or not key:
        print("❌ [錯誤] 找不到 SUPABASE_URL 或 SUPABASE_SERVICE_ROLE_KEY，請檢查 .env 檔案。")
        return

    try:
        # 2. 建立客戶端連線
        supabase: Client = create_client(url, key)
        
        # 3. 準備模擬資料 (Mock Data)
        tw_now = datetime.now(timezone.utc) + timedelta(hours=8)
        now_str = tw_now.strftime('%Y-%m-%d %H:%M:%S')
        
        mock_payload = {
            "category": "test_signal",
            "data": [
                {
                    "sid": "2330",
                    "name": "台積電(測試)",
                    "lp": 1050.0,
                    "pct": 2.5,
                    "ratio": 3.2,
                    "trigger_time": now_str,
                    "industry": "半導體業"
                }
            ],
            "updated_at": now_str
        }

        # 4. 執行寫入 (Upsert)
        print("正在嘗試寫入資料...")
        response = supabase.table("tianji_signals").upsert(mock_payload).execute()
        
        print("✅ [成功] 資料已順利寫入 Supabase！")
        print(f"回傳紀錄: {response.data}")

    except Exception as e:
        print(f"❌ [失敗] 寫入過程發生異常: {str(e)}")

if __name__ == "__main__":
    test_supabase_connection()