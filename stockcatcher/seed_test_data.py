"""
檔案位置：seed_test_data.py
功能說明：天機選股系統 - 測試資料注入與清除腳本
使用方式：
  1. 注入測試資料：python seed_test_data.py --action seed
  2. 清除測試資料：python seed_test_data.py --action clean
"""

import os
import argparse
from dotenv import load_dotenv
from supabase import create_client, Client

# ==========================================
# ⚙️ 1. 環境變數載入與初始化
# ==========================================
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

# 架構師防呆：確保環境變數已正確設置，避免拋出難以追蹤的底層錯誤
if not SUPABASE_URL or not SUPABASE_KEY:
    raise EnvironmentError(
        "❌ [初始化失敗] 缺少 SUPABASE_URL 或 SUPABASE_SERVICE_ROLE_KEY 環境變數，"
        "請確保 .env 檔案存在且設定正確。"
    )

# 建立 Supabase 客戶端實例
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ==========================================
# 📊 2. 測試資料定義 (Mock Data)
# ==========================================
# 嚴格對齊生產環境的 JSONB Schema，確保數值型態 (Float) 的正確性
MOCK_STOCK_ID = "2464"
MOCK_STOCK_NAME = "盟立"

MOCK_PAYLOAD = {
    "stock_id": MOCK_STOCK_ID,
    "stock_name": MOCK_STOCK_NAME,
    "price": 184.0,
    "pct": 3.37,
    "vol_ratio": 3.24,
    "stop_loss": 176.5,
    "industry": "其他電子業",
    "sub_industry": "-", 
    "3k_high": 184.0,
    "pressure_digestion": "85%",
    "energy_slope": "陡增",
    "derivatives": "股期 ✅ | CB ❌"
}

# 準備注入的測試情境 (涵蓋兩種不同策略)
TEST_SCENARIOS = [
    {"category": "warrant_3k", "data": MOCK_PAYLOAD},
    {"category": "volume_3k", "data": MOCK_PAYLOAD}
]

# ==========================================
# 🛠️ 3. 核心業務邏輯：寫入與清除
# ==========================================
def seed_data() -> None:
    """將測試資料寫入 Supabase"""
    print("⏳ [Seed] 開始注入測試資料至 Supabase...")
    success_count = 0

    for payload in TEST_SCENARIOS:
        try:
            supabase.table("tianji_signals").insert(payload).execute()
            print(f"✅ [寫入成功] 策略: {payload['category']} | 標的: {MOCK_STOCK_ID} {MOCK_STOCK_NAME}")
            success_count += 1
        except Exception as e:
            print(f"❌ [寫入失敗] 策略: {payload['category']} | 錯誤: {e}")
    
    print(f"🎉 [完成] 共成功注入 {success_count} 筆測試資料。")


def clean_data() -> None:
    """
    從 Supabase 精準刪除測試資料。
    利用 JSONB 查詢語法，僅刪除 stock_id 為測試股號的紀錄，絕不誤傷正式資料。
    """
    print(f"🧹 [Clean] 準備清除標的為 {MOCK_STOCK_ID} 的測試資料...")
    try:
        # 使用 contains 過濾 JSONB 欄位中的 stock_id，達到精準刪除
        response = supabase.table("tianji_signals") \
            .delete() \
            .contains("data", {"stock_id": MOCK_STOCK_ID}) \
            .execute()
        
        # response.data 會回傳被刪除的資料陣列
        deleted_count = len(response.data) if response.data else 0
        print(f"✅ [清除成功] 已徹底刪除 {deleted_count} 筆測試髒資料。資料庫已恢復潔淨。")

    except Exception as e:
        print(f"❌ [清除失敗] 無法刪除測試資料 | 錯誤: {e}")

# ==========================================
# 🎮 4. CLI 命令列解析入口
# ==========================================
def main():
    """解析終端機指令並分發路由"""
    parser = argparse.ArgumentParser(description="天機選股 - 測試資料管理工具")
    parser.add_argument(
        "--action", 
        choices=["seed", "clean"], 
        required=True, 
        help="選擇動作：'seed' (寫入測試資料) 或 'clean' (刪除測試資料)"
    )
    
    args = parser.parse_args()
    
    if args.action == "seed":
        seed_data()
    elif args.action == "clean":
        clean_data()

if __name__ == "__main__":
    main()