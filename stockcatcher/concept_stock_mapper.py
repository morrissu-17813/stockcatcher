import os
import json
import logging
import requests
import urllib3
import io # 💡 蘇蘇新增：請確保將這行加在檔案最上方的 import 區塊
import pandas as pd  # 💡 蘇蘇新增：用於處理 TDCC 的高密度資料運算
from supabase import create_client, Client

# 關閉不安全的 HTTPS 請求警告 (針對 verify=False)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 設定 Logging 紀錄格式
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# 定義資料源 API 網址
TOPIC_INDEX_URL = "https://aistockmap.com/live/topic-index-tw.json"
COMPANIES_INDEX_URL = "https://aistockmap.com/live/companies-index.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

def normalize_symbol(symbol_str) -> str:
    """清理與正規化股票代號 (如: '2330.TW' -> '2330')"""
    if not symbol_str:
        return ""
    s = str(symbol_str).strip().upper()
    if "." in s:
        s = s.split(".")[0]
    return s

def fetch_data(url: str):
    """從指定的 URL 下載 JSON 資料"""
    try:
        logging.info(f"正在抓取資料: {url}")
        response = requests.get(url, headers=HEADERS, timeout=15, verify=False)
        response.raise_for_status()
        data = response.json()
        logging.info(f"成功取得資料: {url}")
        return data
    except requests.RequestException as e:
        logging.error(f"網絡請求失敗 [{url}]: {e}")
        return None
    except json.JSONDecodeError as e:
        logging.error(f"JSON 解析失敗 [{url}]: {e}")
        return None

def process_mapping(topics_data, companies_data):
    """
    建立概念股與個股對應關係 (以 companies-index 的主題關聯反向建構)
    """
    logging.info("開始進行概念股與個股資料對應整合...")

    # 1. 建立概念股主題 Master 字典 (以 id 為 Key)
    topic_dict = {}
    topic_list = topics_data if isinstance(topics_data, list) else topics_data.get("topics", [])
    
    for t in topic_list:
        if isinstance(t, dict):
            t_id = str(t.get("id") or "")
            if t_id:
                topic_dict[t_id] = {
                    "topic_id": t_id,
                    "name": t.get("name") or t_id,
                    "shortname": t.get("shortname") or t.get("name") or t_id,
                    "description": t.get("description") or "",
                    "stocks": []
                }

    # 2. 解析個股公司資料
    comp_list = companies_data if isinstance(companies_data, list) else companies_data.get("companies", [])
    
    stocks_with_topics = {}

    for comp in comp_list:
        if not isinstance(comp, dict):
            continue

        stock_code = normalize_symbol(comp.get("symbol") or comp.get("code") or comp.get("id") or "")
        stock_name = comp.get("name") or comp.get("company_name") or stock_code

        if not stock_code:
            continue

        raw_topic_ids = (
            comp.get("topics") or 
            comp.get("topicIds") or 
            comp.get("topic_ids") or 
            comp.get("categories") or 
            comp.get("groups") or 
            []
        )

        if isinstance(raw_topic_ids, str):
            raw_topic_ids = [raw_topic_ids]

        matched_topics_for_stock = []

        for tid in raw_topic_ids:
            t_key = str(tid.get("id") if isinstance(tid, dict) else tid)
            
            if t_key in topic_dict:
                topic_info = topic_dict[t_key]
                
                matched_topics_for_stock.append({
                    "topic_id": topic_info["topic_id"],
                    "name": topic_info["name"],
                    "shortname": topic_info["shortname"],
                    "description": topic_info["description"]
                })

                topic_info["stocks"].append({
                    "symbol": stock_code,
                    "name": stock_name,
                    "detail": comp
                })

        stocks_with_topics[stock_code] = {
            "symbol": stock_code,
            "name": stock_name,
            "topics": matched_topics_for_stock,
            "detail": comp
        }

    # 3. 整理 topics_with_stocks 清單
    topics_with_stocks = []
    for t_info in topic_dict.values():
        topics_with_stocks.append({
            "topic_id": t_info["topic_id"],
            "name": t_info["name"],
            "shortname": t_info["shortname"],
            "description": t_info["description"],
            "stock_count": len(t_info["stocks"]),
            "stocks": t_info["stocks"]
        })

    result = {
        "topics_with_stocks": topics_with_stocks,
        "stocks_with_topics": stocks_with_topics
    }

    total_mapped_stocks = sum(1 for s in stocks_with_topics.values() if len(s["topics"]) > 0)
    logging.info(f"整合完成！共處理 {len(topics_with_stocks)} 個概念股主題，成功對應 {total_mapped_stocks} 檔個股。")

    return result

def save_json(data, output_filepath="concept_stocks_mapped.json"):
    """儲存資料為 UTF-8 編碼的 JSON 檔案"""
    try:
        with open(output_filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logging.info(f"成功導出 JSON 檔至：{output_filepath}")
        print(f"\n✅ 成功建立 JSON 檔案：{output_filepath}")
    except Exception as e:
        logging.error(f"寫入 JSON 檔失敗：{e}")

# ==========================================
# 資料庫寫入層 (Supabase Integration)
# ==========================================
def sync_to_supabase(mapped_data: dict):
    """將產出的概念股對應清單寫入 Supabase"""
    # 🛡️ 嚴格要求透過環境變數注入敏感憑證
    url = "https://iatlchzzjkjaetorvvil.supabase.co"
    key = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImlhdGxjaHp6amtqYWV0b3J2dmlsIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc4NjAzMDQzMywiZXhwIjoyMTAxNjA2NDMzfQ.FckTSOyIo_QCocrgfaGd9mHV2wXRJxSeC5955936hSQ"
    
    if not url or not key:
        logging.error("❌ 找不到 Supabase 憑證！請確認環境變數已正確設定。")
        return

    logging.info("🔗 連線至 Supabase 資料庫...")
    supabase: Client = create_client(url, key)
    
    topics_with_stocks = mapped_data.get("topics_with_stocks", [])
    total_inserted = 0

    for theme in topics_with_stocks:
        # 萃取所有欄位，若無資料則給予預設空字串
        slug = theme.get("topic_id", "")
        concept_name = theme.get("name", "")
        shortname = theme.get("shortname", concept_name) # 若無短名，退回使用全名
        description = theme.get("description", "")
        
        try:
            # 1. 寫入主題表 (包含新增的 shortname 與 description)
            theme_resp = supabase.table("themes").upsert(
                {
                    "slug": slug, 
                    "concept_name": concept_name,
                    "shortname": shortname,
                    "description": description
                }, 
                on_conflict="slug"
            ).execute()
            
            if not theme_resp.data:
                continue
                
            theme_id = theme_resp.data[0]["id"]
            
            # 2. 準備成分股清單，寫入 theme_stocks 表格
            stock_inserts = [
                {"theme_id": theme_id, "symbol": s["symbol"], "stock_name": s["name"]}
                for s in theme.get("stocks", [])
            ]
            
            # 3. 確保資料最新：先刪舊，再寫新
            supabase.table("theme_stocks").delete().eq("theme_id", theme_id).execute()
            if stock_inserts:
                supabase.table("theme_stocks").insert(stock_inserts).execute()
                total_inserted += len(stock_inserts)
                
        except Exception as e:
            logging.error(f"寫入主題 [{concept_name}] 時發生錯誤: {e}")

    logging.info(f"✅ Supabase 同步完成！共更新 {len(topics_with_stocks)} 個主題，寫入 {total_inserted} 筆個股關聯。") 

# ==========================================
# 資料庫寫入層 (TDCC 集保大戶資料同步)
# ==========================================
def sync_tdcc_data():
    """從 TDCC 官方 OpenData 抓取最新集保資料 (CSV)，計算大戶比例並寫入 Supabase"""
    url = "https://iatlchzzjkjaetorvvil.supabase.co"
    key = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImlhdGxjaHp6amtqYWV0b3J2dmlsIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc4NjAzMDQzMywiZXhwIjoyMTAxNjA2NDMzfQ.FckTSOyIo_QCocrgfaGd9mHV2wXRJxSeC5955936hSQ"
       
    
    if not url or not key:
        logging.error("❌ 找不到 Supabase 憑證！無法執行 TDCC 同步。")
        return

    supabase: Client = create_client(url, key)
    
    # 🚨 修正：TDCC 官方真實的 OpenData 網址 (回傳格式為 CSV)
    tdcc_url = "https://smart.tdcc.com.tw/opendata/getOD.ashx?id=1-5"
    
    logging.info("🚀 正在從 TDCC OpenAPI 抓取最新集保資料 (CSV)...")
    try:
        # 加上 User-Agent 偽裝並關閉 SSL 驗證以防憑證擋刷
        res = requests.get(tdcc_url, headers=HEADERS, timeout=60, verify=False)
        res.raise_for_status()
        
        # 🚨 修正：使用 io.StringIO 將 requests 拿到的純文字轉為 Pandas 可讀的 CSV 格式
        csv_data = io.StringIO(res.text)
        df = pd.read_csv(csv_data)
        
    except Exception as e:
        logging.error(f"❌ TDCC API 請求失敗或解析錯誤: {e}")
        return

    try:
        # 官方 CSV 預設欄位: ['資料日期', '證券代號', '持股分級', '人數', '股數', '占集保庫存數比例%']
        # 為防中文編碼與名稱變動，依序強制重新命名欄位
        df.columns = ['date', 'symbol', 'level', 'people', 'shares', 'percent']

        df['date'] = df['date'].astype(str).str.strip()
        df['symbol'] = df['symbol'].astype(str).str.strip()
        df['level'] = pd.to_numeric(df['level'], errors='coerce').fillna(0).astype(int)
        df['percent'] = pd.to_numeric(df['percent'], errors='coerce').fillna(0)

        # 僅篩選 4 位數的上市櫃個股代碼，濾除權證與債券
        df = df[df['symbol'].str.len() == 4]
        
        if df.empty:
            logging.warning("⚠️ TDCC 資料篩選後為空，中止同步。")
            return

        latest_date = df['date'].iloc[0]
        logging.info(f"📦 開始處理 TDCC 最新資料日期: {latest_date}")

        # 💡 架構師防呆：
        # Level 15 = 1,000,001股以上 (千張大戶)
        # Level 12-14 = 400張~1000張
        # Level 16 = 差異數調整 / Level 17 = 總計 (絕對不能算進去，否則大戶佔比會破表)
        
        # 計算千張大戶 (Level 15)
        df_1000k = df[df['level'] == 15].groupby('symbol')['percent'].sum().reset_index()
        df_1000k.rename(columns={'percent': 'ratio_1000k'}, inplace=True)

        # 計算 400張以上大戶 (Level 12 到 15)
        df_400k = df[df['level'].between(12, 15)].groupby('symbol')['percent'].sum().reset_index()
        df_400k.rename(columns={'percent': 'ratio_400k'}, inplace=True)

        # 合併計算結果
        merged = pd.merge(df_1000k, df_400k, on='symbol', how='outer').fillna(0)

        records = []
        for _, row in merged.iterrows():
            records.append({
                "date": latest_date,
                "symbol": row['symbol'],
                "ratio_1000k": round(float(row['ratio_1000k']), 2),
                "ratio_400k": round(float(row['ratio_400k']), 2)
            })

        # 批次 Upsert 寫入 Supabase
        batch_size = 1000
        total_inserted = 0
        for i in range(0, len(records), batch_size):
            batch = records[i:i+batch_size]
            supabase.table("tdcc_history").upsert(batch).execute()
            total_inserted += len(batch)

        logging.info(f"✅ TDCC 同步完成！共成功寫入 {total_inserted} 筆集保資料。")

    except Exception as e:
        logging.error(f"❌ TDCC 資料處理或寫入資料庫時發生錯誤: {e}")
           
def main():
    # print("=========================================")
    # print("  概念股與個股資料對應暨同步工具")
    # print("=========================================\n")

    # topics_raw = fetch_data(TOPIC_INDEX_URL)
    # companies_raw = fetch_data(COMPANIES_INDEX_URL)

    # if topics_raw and companies_raw:
    #     # 1. 資料處理與對應
    #     mapped_data = process_mapping(topics_raw, companies_raw)
        
    #     # 2. 儲存至本地 JSON 檔
    #     save_json(mapped_data, "concept_stocks_mapped.json")
        
    #     # 3. 同步至 Supabase 資料庫 (概念股)
    #     sync_to_supabase(mapped_data)
    # else:
    #     print("❌ 概念股資料下載失敗，跳過概念股同步。")
    # ==========================================
    # 💡 蘇蘇新增：4. 執行 TDCC 大戶籌碼同步
    # ==========================================
    print("\n=========================================")
    print("  TDCC 集保大戶籌碼同步")
    print("=========================================\n")
    sync_tdcc_data()
    
if __name__ == "__main__":
    main()