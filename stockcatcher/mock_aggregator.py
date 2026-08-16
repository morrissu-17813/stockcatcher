"""
mock_aggregator.py
角色：程式小幫手-蘇蘇 (全端軟體工程師)
目的：模擬盤中 TIDE 即時運算大腦 (Aggregator)。
      每 15 秒將模擬的族群共振數據 Upsert 到 Supabase 的 system_cache 表中，
      做為前端 LINE Webhook 的極速快取來源。
安全性規範：所有憑證均從環境變數 (.env) 安全讀取，嚴禁硬編碼。
"""

import asyncio
import logging
import os
from datetime import datetime
from supabase import create_client, Client
from dotenv import load_dotenv

# 載入本地端的 .env 檔案
load_dotenv()

# 初始化日誌系統，方便終端機監控狀態與除錯
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(levelname)s - [%(funcName)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

async def run_mock_brain():
    """執行非同步的盤中模擬大腦"""
    
    # 1. 安全讀取 Supabase 連線憑證
    supabase_url = os.environ.get("SUPABASE_URL")
    supabase_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    
    if not supabase_url or not supabase_key:
        logger.error("❌ 找不到 Supabase 憑證！請確認 .env 檔案已正確設定。")
        return

    # 2. 初始化 Supabase 客戶端
    client: Client = create_client(supabase_url, supabase_key)
    logger.info("🧠 盤中模擬大腦已啟動，開始向 Supabase (system_cache) 推送快取訊號...")

    try:
        while True:
            # 3. 模擬即時運算出的 TIDE 分數結果 (字典結構，準備轉入 JSONB)
            mock_data = {
                "update_time": datetime.now().strftime("%H:%M:%S"),
                "top1_name": "矽光子 / CPO",
                "top1_score": "98.2",
                "top1_leader": "華星光(4979) +漲停 | 發動率：83%"
            }
            
            # 4. 執行 Upsert，將快取寫入資料庫
            try:
                # 使用 cache_key='tide_top_5' 作為唯一識別碼，確保覆寫而不重複新增
                # Supabase Python SDK 會自動處理字典轉 JSONB 的動作
                response = client.table("system_cache").upsert({
                    "cache_key": "tide_top_5",
                    "cache_value": mock_data
                }).execute()
                
                logger.info(f"✅ 已成功推送最新 TIDE 數據至 Supabase (更新時間: {mock_data['update_time']})")
            except Exception as db_err:
                logger.warning(f"⚠️ 資料庫寫入異常 (可能為瞬間網路波動): {db_err}")
            
            # 5. 降頻寫入保護機制：每 15 秒更新一次，避免資料庫 WAL 負載過高
            await asyncio.sleep(15)
            
    except asyncio.CancelledError:
        logger.info("🛑 收到中止訊號，模擬大腦準備關閉...")
    except Exception as e:
        logger.error(f"❌ 發生非預期異常: {e}")
    finally:
        logger.info("💤 大腦已停止運作。")

if __name__ == "__main__":
    # 標準的 asyncio 啟動與優雅關閉寫法
    try:
        asyncio.run(run_mock_brain())
    except KeyboardInterrupt:
        logger.info("🛑 使用者手動中斷程式 (Ctrl+C)。")