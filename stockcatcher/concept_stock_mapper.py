import json
import logging
import requests
import urllib3

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

        # 嘗試讀取個股隸屬的概念股主題 ID 列表
        raw_topic_ids = (
            comp.get("topics") or 
            comp.get("topicIds") or 
            comp.get("topic_ids") or 
            comp.get("categories") or 
            comp.get("groups") or 
            []
        )

        # 若單個主題是以字串呈現
        if isinstance(raw_topic_ids, str):
            raw_topic_ids = [raw_topic_ids]

        matched_topics_for_stock = []

        for tid in raw_topic_ids:
            t_key = str(tid.get("id") if isinstance(tid, dict) else tid)
            
            # 若對應到概念股 Master 字典
            if t_key in topic_dict:
                topic_info = topic_dict[t_key]
                
                # 更新個股列表
                matched_topics_for_stock.append({
                    "topic_id": topic_info["topic_id"],
                    "name": topic_info["name"],
                    "shortname": topic_info["shortname"],
                    "description": topic_info["description"]
                })

                # 反向加入概念股主題下的股票陣列
                topic_info["stocks"].append({
                    "symbol": stock_code,
                    "name": stock_name,
                    "detail": comp
                })

        # 更新 stocks_with_topics
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

    # 診斷提醒：若仍然無對應，輸出第一檔個股資料結構供除錯
    if total_mapped_stocks == 0 and len(comp_list) > 0:
        logging.warning("⚠️ 警告：個股對應數量仍為 0！以下為第一檔個股公司的原始欄位結構供參考：")
        print(json.dumps(comp_list[0], ensure_ascii=False, indent=2))

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

def main():
    print("=========================================")
    print("  概念股與個股資料對應工具")
    print("=========================================\n")

    topics_raw = fetch_data(TOPIC_INDEX_URL)
    companies_raw = fetch_data(COMPANIES_INDEX_URL)

    if not topics_raw or not companies_raw:
        print("❌ 資料下載失敗，請檢查網路連線或 API 狀態。")
        return

    mapped_data = process_mapping(topics_raw, companies_raw)
    save_json(mapped_data, "concept_stocks_mapped.json")

if __name__ == "__main__":
    main()

