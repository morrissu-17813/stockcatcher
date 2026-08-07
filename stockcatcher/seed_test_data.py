"""
檔案位置：seed_test_data.py
功能說明：天機選股系統 - 批次測試資料注入與精準清除腳本 (10筆複合情境)
使用方式：
  1. 注入測試資料：python seed_test_data.py --action seed
  2. 清除測試資料：python seed_test_data.py --action clean
"""

import os
import argparse
from dotenv import load_dotenv
from supabase import create_client, Client

# ==========================================
# ⚙️ 1. 環境變數載入與系統初始化
# ==========================================
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

# 架構師防呆：提早攔截環境變數缺失，避免底層連線超時
if not SUPABASE_URL or not SUPABASE_KEY:
    raise EnvironmentError(
        "❌ [初始化失敗] 缺少 SUPABASE_URL 或 SUPABASE_SERVICE_ROLE_KEY，"
        "請確保 .env 檔案存在且設定正確。"
    )

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ==========================================
# 📊 2. 測試資料集定義 (10 筆多樣化情境)
# ==========================================
TEST_SCENARIOS = [
    # --- 策略一：權證主力標的 (warrant_3k) ---
    {
        "category": "warrant_3k",
        "data": {"stock_id": "2330", "stock_name": "台積電", "price": 1050.0, "pct": 1.5, "vol_ratio": 1.8, "stop_loss": 1020.0, "industry": "半導體業", "sub_industry": "晶圓代工", "3k_high": 1055.0, "pressure_digestion": "95%", "energy_slope": "平穩", "derivatives": "股期 ✅ | CB ❌"}
    },
    {
        "category": "warrant_3k",
        "data": {"stock_id": "2317", "stock_name": "鴻海", "price": 210.5, "pct": 4.2, "vol_ratio": 3.5, "stop_loss": 200.0, "industry": "其他電子業", "sub_industry": "EMS", "3k_high": 212.0, "pressure_digestion": "80%", "energy_slope": "陡增", "derivatives": "股期 ✅ | CB ❌"}
    },
    {
        "category": "warrant_3k",
        "data": {"stock_id": "2454", "stock_name": "聯發科", "price": 1280.0, "pct": -1.2, "vol_ratio": 0.9, "stop_loss": 1250.0, "industry": "半導體業", "sub_industry": "IC設計", "3k_high": 1300.0, "pressure_digestion": "40%", "energy_slope": "衰退", "derivatives": "股期 ✅ | CB ❌"}
    },
    {
        "category": "warrant_3k",
        "data": {"stock_id": "3231", "stock_name": "緯創", "price": 115.0, "pct": 6.8, "vol_ratio": 5.2, "stop_loss": 108.0, "industry": "電腦及週邊設備業", "sub_industry": "伺服器", "3k_high": 116.5, "pressure_digestion": "99%", "energy_slope": "陡增", "derivatives": "股期 ✅ | CB ✅"}
    },
    {
        "category": "warrant_3k",
        "data": {"stock_id": "2382", "stock_name": "廣達", "price": 285.0, "pct": 2.1, "vol_ratio": 2.1, "stop_loss": 275.0, "industry": "電腦及週邊設備業", "sub_industry": "伺服器", "3k_high": 290.0, "pressure_digestion": "65%", "energy_slope": "平穩", "derivatives": "股期 ✅ | CB ❌"}
    },

    # --- 策略二：3K突破 + 量能異常 (volume_3k) ---
    {
        "category": "volume_3k",
        "data": {"stock_id": "2603", "stock_name": "長榮", "price": 188.5, "pct": 8.5, "vol_ratio": 6.7, "stop_loss": 170.0, "industry": "航運業", "sub_industry": "貨櫃航運", "3k_high": 188.5, "pressure_digestion": "100%", "energy_slope": "陡增", "derivatives": "股期 ✅ | CB ❌"}
    },
    {
        "category": "volume_3k",
        "data": {"stock_id": "1519", "stock_name": "華城", "price": 920.0, "pct": 9.8, "vol_ratio": 8.1, "stop_loss": 840.0, "industry": "電機機械", "sub_industry": "重電", "3k_high": 920.0, "pressure_digestion": "100%", "energy_slope": "陡增", "derivatives": "股期 ✅ | CB ❌"}
    },
    {
        "category": "volume_3k",
        "data": {"stock_id": "3324", "stock_name": "雙鴻", "price": 710.0, "pct": 3.4, "vol_ratio": 2.8, "stop_loss": 680.0, "industry": "電腦及週邊設備業", "sub_industry": "散熱模組", "3k_high": 725.0, "pressure_digestion": "70%", "energy_slope": "平穩", "derivatives": "股期 ✅ | CB ✅"}
    },
    {
        "category": "volume_3k",
        "data": {"stock_id": "3017", "stock_name": "奇鋐", "price": 645.0, "pct": 1.1, "vol_ratio": 1.5, "stop_loss": 630.0, "industry": "電腦及週邊設備業", "sub_industry": "散熱模組", "3k_high": 655.0, "pressure_digestion": "55%", "energy_slope": "平穩", "derivatives": "股期 ✅ | CB ✅"}
    },
    {
        "category": "volume_3k",
        "data": {"stock_id": "2362", "stock_name": "藍天", "price": 58.6, "pct": -0.5, "vol_ratio": 0.8, "stop_loss": 57.0, "industry": "電腦及週邊設備業", "sub_industry": "PC代工", "3k_high": 60.2, "pressure_digestion": "30%", "energy_slope": "衰退", "derivatives": "股期 ❌ | CB ✅"}
    }
]

# ==========================================
# 🛠️ 3. 核心業務邏輯：批次寫入與動態清除
# ==========================================
def seed_data() -> None:
    """將測試資料寫入 Supabase (O(N) 批次寫入)"""
    print(f"⏳ [Seed] 開始注入 {len(TEST_SCENARIOS)} 筆測試資料至 Supabase...")
    success_count = 0

    for payload in TEST_SCENARIOS:
        try:
            supabase.table("tianji_signals").insert(payload).execute()
            stock_id = payload['data']['stock_id']
            stock_name = payload['data']['stock_name']
            print(f"✅ [寫入成功] 策略: {payload['category']:<12} | 標的: {stock_id} {stock_name}")
            success_count += 1
        except Exception as e:
            print(f"❌ [寫入失敗] 策略: {payload['category']} | 錯誤: {e}")
    
    print(f"🎉 [完成] 共成功注入 {success_count} 筆測試資料。請前往 LINE 測試。")

def clean_data() -> None:
    """
    動態萃取測試集中的 stock_id，並精準刪除對應的資料。
    避免刪除到正式環境中其他的真實數據。
    """
    # 提取所有測試資料的唯一股號集合
    test_stock_ids = set(item["data"]["stock_id"] for item in TEST_SCENARIOS)
    
    print(f"🧹 [Clean] 準備清除以下測試標的紀錄: {', '.join(test_stock_ids)}")
    total_deleted = 0

    for sid in test_stock_ids:
        try:
            response = supabase.table("tianji_signals") \
                .delete() \
                .contains("data", {"stock_id": sid}) \
                .execute()
            
            deleted_count = len(response.data) if response.data else 0
            if deleted_count > 0:
                print(f"✅ [清除成功] 已移除標的 {sid} 的 {deleted_count} 筆髒資料。")
                total_deleted += deleted_count
        except Exception as e:
            print(f"❌ [清除失敗] 標的 {sid} 無法刪除 | 錯誤: {e}")

    print(f"✨ [完成] 資料庫清理完畢，共移除 {total_deleted} 筆測試紀錄。")

# ==========================================
# 🎮 4. CLI 命令列解析入口
# ==========================================
def main():
    """解析終端機指令並分發路由"""
    parser = argparse.ArgumentParser(description="天機選股 - 批次測試資料管理工具")
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