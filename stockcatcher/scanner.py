import os
import json
import time
import requests # 確保檔案最上方有 import requests
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from fugle_marketdata import WebSocketClient, RestClient
from line_test import send_3k_alert 
from telegram_test import send_tg_alert

# --- 1. 環境設定 ---
load_dotenv()
FUGLE_API_KEY = os.getenv("FUGLE_API_KEY")

# 全域變數：儲存監控狀態與個股資訊
monitor_data = {}
stock_info_map = {}

# --- 2. 核心功能：抓取今日目標清單 ---
def get_top_stocks_info(api_key):
    print("🔍 正在嘗試多重路徑抓取今日強勢熱門股...")
    headers = {"X-API-KEY": api_key}
    
    # 這是目前最有可能的兩個 v0.3 正確路徑
    possible_urls = [
        # 1. 最標準的 v0.3 即時排行路徑
        "https://api.fugle.tw/marketdata/v0.3/stock/intraday/rankings/volumes",
        # 2. 舊版的 query string 格式
        "https://api.fugle.tw/marketdata/v0.3/stock/intraday/rankings?type=volumes",
        # 3. 如果是新版 v1.0
        "https://api.fugle.tw/marketdata/v1.0/stock/intraday/rankings/volumes"
    ]
    
    candidates = []
    
    for url in possible_urls:
        try:
            print(f"📡 嘗試連線：{url}")
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                data = response.json()
                # 取得前 50 檔代號
                candidates = [item['symbol'] for item in data.get('data', [])][:50]
                if candidates:
                    print(f"✨ 成功！從路徑找到 {len(candidates)} 檔標的")
                    break # 抓到就跳出迴圈
            else:
                print(f"💡 此路徑狀態碼: {response.status_code}")
        except Exception as e:
            print(f"❓ 連線異常: {e}")

    # --- 最終防線：如果 API 都沒回應 ---
    if not candidates:
        print("🚩 警告：API 路徑皆無法連通，切換至備用候選名單。")
        # 幫你更新了更強大的備用名單
        candidates = ["2313", "2455", "6568", "5222", "2609", "2303", "2382", "3231", "2455", "3037"]

    # --- 下載個股基本資料 ---
    from fugle_marketdata import RestClient
    rest_client = RestClient(api_key=api_key)
    mapping = {}
    print("📦 正在下載個股基本面資料...")
    
    for symbol in candidates:
        try:
            meta = rest_client.stock.intraday.meta(symbol=symbol)
            name = meta.get("nameZh") or meta.get("name") or symbol
            mapping[symbol] = {
                "name": name,
                "industry": meta.get("industryZh") or "其他",
                "themes": "動態監控標的"
            }
            time.sleep(0.05) 
        except:
            mapping[symbol] = {"name": symbol, "industry": "未知", "themes": "監控中"}

    print(f"✅ 初始化完成！目前監控：{', '.join([m['name'] for m in mapping.values()][:5])} ...")
    return mapping
# --- 3. 策略判斷：處理每一筆即時報價 ---
def handle_message(message):
    global monitor_data, stock_info_map
    # 取得 UTC 時間並轉為台灣時間 (+8)   
    now_tw = datetime.now(timezone.utc) + timedelta(hours=8)
    # 解析 JSON
    if isinstance(message, str):
        data = json.loads(message)
    else:
        data = message

    event = data.get("event")
    if event in ["authenticated", "heartbeat"]:
        return

    # 處理報價數據
    if event == "data" and data.get("resource") == "stock.intraday.quote":
        quote = data.get("data", {})
        symbol = quote.get("symbol")
        price = quote.get("lastPrice")
        
        if not symbol or price is None:
            return

        info = stock_info_map.get(symbol, {"name": symbol, "industry": "未知", "themes": "觀察中"})

        # 時間判斷邏輯        
        now = now_tw.time()        
        start_time = datetime.strptime("09:00", "%H:%M").time()
        check_time = datetime.strptime("09:15", "%H:%M").time()
        end_time = datetime.strptime("13:30", "%H:%M").time()

        # A. 09:00 ~ 09:15 紀錄區間高低
        if start_time <= now <= check_time:
            if price > monitor_data[symbol]["high"]:
                monitor_data[symbol]["high"] = price
            if price < monitor_data[symbol]["low"]:
                monitor_data[symbol]["low"] = price
            
            # 每隔一段時間在終端機顯示一次紀錄狀態（避免洗屏）
            if int(time.time()) % 10 == 0:
                print(f"🕒 [紀錄中] {info['name']} 區間高: {monitor_data[symbol]['high']}")

        # B. 09:15 ~ 13:30 判斷突破
        elif check_time < now <= end_time:
        # elif True:  # 測試用，強制進入判斷
            if not monitor_data[symbol]["triggered"] and monitor_data[symbol]["high"] > 0:
                h15 = monitor_data[symbol]["high"]
                l15 = monitor_data[symbol]["low"]

                # 多頭突破
                if price > h15:
                    print(f"🚀 {info['name']} 多頭突破！現價: {price}")
                    stop_loss = max(l15, round(h15 * 0.975, 2)) # 停損設在 15 分低或 2.5% 處
                    # 1. 保留原本的 Line 推播
                    send_3k_alert(
                        stock_id=f"{symbol} {info['name']}",
                        trend="📈 盤中 3K 多頭突破",
                        price=price,
                        limit_price=h15,
                        stop_loss=stop_loss,
                        industry=info['industry'],
                        themes=info['themes']
                    )
                    # 2. 新增 Telegram 推播
                    send_tg_alert(
                        f"{symbol} {info['name']}", "盤中 3K 多頭突破", 
                        price, h15, stop_loss, info['industry'], info['themes']
                    )
                    monitor_data[symbol]["triggered"] = True
                
                # 空頭跌破
                elif price < l15:
                    print(f"💀 {info['name']} 空頭跌破！現價: {price}")
                    stop_loss = min(h15, round(l15 * 1.025, 2))
                    send_3k_alert(
                        stock_id=f"{symbol} {info['name']}",
                        trend="📉 盤中 3K 空頭跌破",
                        price=price,
                        limit_price=l15,
                        stop_loss=stop_loss,
                        industry=info['industry'],
                        themes=info['themes']
                    )
                    monitor_data[symbol]["triggered"] = True

# --- 4. 主程式啟動 ---
def main():
    global stock_info_map, monitor_data
    
    if not FUGLE_API_KEY:
        print("❌ 錯誤：找不到 API Key，請檢查 .env 檔案。")
        return

    # 1. 取得標的與資訊
    stock_info_map = get_top_stocks_info(FUGLE_API_KEY)
    
    # 2. 初始化監控狀態
    monitor_data = {
        sid: {"high": 0, "low": 9999, "triggered": False} 
        for sid in stock_info_map.keys()
    }
    
    # 3. 建立 WebSocket 連線
    client = WebSocketClient(api_key=FUGLE_API_KEY)
    stock = client.stock
    
    def on_open():
        print(f"✅ 連線成功！正在監控 {len(stock_info_map)} 檔個股...")
        for sid in stock_info_map.keys():
            stock.subscribe({"type": "quote", "symbol": sid})

    stock.on("open", on_open)
    stock.on("message", handle_message)
    stock.on("error", lambda err: print(f"❌ 錯誤: {err}"))
    stock.on("close", lambda: print("🔌 連線已關閉"))

    print("🚀 StockCatcher 啟動中，等待數據...")
    stock.connect()

if __name__ == "__main__":
    main()