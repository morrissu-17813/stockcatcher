import os
import json
import time
import requests # 確保檔案最上方有 import requests
import re
# import pandas as pd
from bs4 import BeautifulSoup
from datetime import time as dtime
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

def send_tg_msg(message):
    """ 發送訊息到 Telegram """
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    
    # 檢查有沒有設定金鑰，沒設定就不發送
    if not token or not chat_id:
        print("⚠️ 找不到 Telegram Token 或 Chat ID，略過發送。")
        return

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML"
    }
    
    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            print("📤 Telegram 訊息發送成功！")
        else:
            print(f"❌ TG 發送失敗，狀態碼：{response.status_code}, 回應：{response.text}")
    except Exception as e:
        print(f"❌ TG 連線異常：{e}")
# --- 2. 核心功能：抓取今日目標清單 ---
def fetch_yahoo_rankings():
    """ 爬取 Yahoo 奇摩股市 - 成交量排行 (防呆過濾版) """
    try:
        print("🌐 正在從 Yahoo 奇摩股市抓取成交量排行...")
        url = "https://tw.stock.yahoo.com/rank/volume"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        res = requests.get(url, headers=headers, timeout=10)
        
        # 準備一個空的容器裝代號
        candidates = []
        
        # --- 方法 1：從網址路徑提取 (最精準) ---
        soup = BeautifulSoup(res.text, 'html.parser')
        links = soup.find_all('a', href=True)
        for link in links:
            href = link['href']
            # 尋找包含 /stock/ 或 /quote/ 後接數字的路徑
            match = re.search(r'/(?:stock|quote)/(\d{4,6})', href)
            if match:
                s = match.group(1)  # 抓到代號了
                # 🛡️ 關鍵過濾：長度必須為 4 且不是年份
                if len(s) == 4 and s not in ['2024', '2025', '2026']:
                    if s not in candidates:
                        candidates.append(s)
        
        # --- 方法 2：如果方法 1 沒抓到，改用文字掃描 (最暴力) ---
        if not candidates:
            print("⚠️ 路徑提取失敗，嘗試文字掃描法...")
            # 尋找全文中所有 4 到 6 位的數字
            all_numbers = re.findall(r'\b\d{4,6}\b', res.text)
            # 🛡️ 關鍵過濾：長度必須為 4 且不是年份
            candidates = [n for n in all_numbers if len(n) == 4 and n not in ['2024', '2025', '2026']]

        # 移除重複項並只取前 50 檔
        final_list = list(dict.fromkeys(candidates))[:50]
        
        if final_list:
            print(f"✨ 成功！經過過濾後提取到 {len(final_list)} 檔純淨標的")
            return final_list
        else:
            print("🚩 Yahoo 頁面目前無有效數據")
            return []
            
    except Exception as e:
        # 這裡會印出具體的錯誤原因，方便我們除錯
        print(f"❌ Yahoo 抓取異常: {e}")
        return []
def fetch_finmind_rankings(token=""):
    """ 從 FinMind 抓取今日熱門股 (輕量版，不需 pandas) """
    try:
        print("📊 正在從 FinMind 抓取今日熱門標的...")
        url = "https://api.finmindtrade.com/api/v4/data"
        parameter = {
            "dataset": "TaiwanStockHot", 
            "token": token
        }
        resp = requests.get(url, params=parameter)
        data = resp.json()
        if data.get('msg') == 'success':
            # 直接從 list of dict 中取出 stock_id
            raw_list = [item['stock_id'] for item in data.get('data', [])]
            # 去重並取前 50
            return list(dict.fromkeys(raw_list))[:50]
        return []
    except Exception as e:
        print(f"❌ FinMind 抓取失敗: {e}")
        return []
def get_top_stocks_info(api_key, finmind_token=""):
    print("🚀 [混合模式] 啟動多源選股引擎...")
    
    # 核心指定標的 (你的必看名單)
    my_must_watch = ["2313", "2455", "6568", "5222","2340","6261"]
    
    # --- 策略：層級式抓取 ---
    # 1. 先試 Yahoo (最即時)
    candidates = fetch_yahoo_rankings()
    
    # 2. Yahoo 失敗則試 FinMind
    if not candidates:
        candidates = fetch_finmind_rankings(finmind_token)
        
    # 3. 若都失敗，才用富果官方 (或備援)
    if not candidates:
        print("⚠️ 外部來源皆失敗，嘗試富果官方 API...")
        # ... 這裡放你原本的富果排行抓取邏輯 ...
        pass

    # 合併清單：必看 4 檔 + 抓到的熱門股 (去重)
    final_list = list(dict.fromkeys(my_must_watch + (candidates or [])))[:50]
    
    # 最終備援防線
    if not final_list:
        final_list = my_must_watch + ["2330", "2317", "2454", "2603", "2609"]

    # --- 呼叫富果 API 獲取 Meta 資訊 (這部分權限通常沒問題) ---
    rest_client = RestClient(api_key=api_key)
    mapping = {}
    print(f"📦 正在透過富果 API 同步 {len(final_list)} 檔個股 Meta 資料...")
    
    for symbol in final_list:
        try:
            meta = rest_client.stock.intraday.meta(symbol=symbol)
            mapping[symbol] = {
                "name": meta.get("nameZh", symbol),
                "industry": meta.get("industryZh", "其他"),
                "themes": "外部排行強勢股"
            }
            time.sleep(0.05) 
        except:
           mapping[symbol] = {"name": symbol, "industry": "未知", "themes": "觀察中"}

    print(f"✅ 選股完成！目前監控：{', '.join([m['name'] for m in mapping.values()][:8])}...")
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
        if symbol and price:
            # 💡 [關鍵偵錯行]：這行會讓你在 GitHub Log 看到即時跳動的數字
           print(f"📡 [收訊正常] {symbol} 目前價: {price}", flush=True)
        if not symbol or price is None:
            return

        info = stock_info_map.get(symbol, {"name": symbol, "industry": "未知", "themes": "觀察中"})

        # 時間判斷邏輯        
        now = now_tw.time()        
        start_time = datetime.strptime("09:00", "%H:%M").time()
        check_time = datetime.strptime("09:15", "%H:%M").time()
        end_time = datetime.strptime("13:30", "%H:%M").time()

        # A. 09:00 ~ 09:15 紀錄區間高低
        if dtime(9, 0) <= now <= dtime(9, 15):
            if price > monitor_data[symbol]["high"]:
                monitor_data[symbol]["high"] = price
            if price < monitor_data[symbol]["low"]:
                monitor_data[symbol]["low"] = price
            
            # 每隔一段時間在終端機顯示一次紀錄狀態（避免洗屏）
            if int(time.time()) % 10 == 0:
                print(f"🕒 [紀錄中] {info['name']} 區間高: {monitor_data[symbol]['high']}")

        # B. 09:15 ~ 13:30 判斷突破
        # elif dtime(9, 15) < now <= dtime(13, 30):
        elif True:  # 測試用，強制進入判斷
            if not monitor_data[symbol]["triggered"] and monitor_data[symbol]["high"] > 0:
                h15 = monitor_data[symbol]["high"]
                l15 = monitor_data[symbol]["low"]

                # 多頭突破
                if price > h15:
                    print(f"🚀 {info['name']} 多頭突破！現價: {price}")
                    stop_loss = max(l15, round(h15 * 0.975, 2))
                    
                    # 💡 使用 .get() 安全取值
                    s_industry = info.get('industry', '未知')
                    s_themes = info.get('themes', '觀察中')

                    send_3k_alert(
                        stock_id=f"{symbol} {info['name']}",
                        trend="📈 盤中 3K 多頭突破",
                        price=price,
                        limit_price=h15,
                        stop_loss=stop_loss,
                        industry=s_industry, # 改用安全變數
                        themes=s_themes      # 改用安全變數
                    )
                    
                    send_tg_alert(
                        f"{symbol} {info['name']}", "盤中 3K 多頭突破", 
                        price, h15, stop_loss, s_industry, s_themes
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
    load_dotenv()
    api_key = os.getenv("FUGLE_API_KEY")

    # 1. 取得標的與資訊
    stock_info_map = get_top_stocks_info(api_key)
    
    # 2. 💡 [強化邏輯]：初始化監控狀態，並先用 REST 抓取目前的區間高低
    rest_client = RestClient(api_key=api_key)
    monitor_data = {}
    
    print("⏳ 正在初始化區間數據 (H15/L15)...")
    for sid in stock_info_map.keys():
        try:
            # 抓取當日的日線/區間資料作為保險
            quote = rest_client.stock.intraday.quote(symbol=sid)
            day_high = quote.get("highPrice", 0)
            day_low = quote.get("lowPrice", 9999)
            
            # 如果現在已經過 09:15，直接把目前的最高價當作基準
            monitor_data[sid] = {"high": day_high, "low": day_low, "triggered": False}
        except:
            monitor_data[sid] = {"high": 0, "low": 9999, "triggered": False}
    
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
    send_tg_msg("🤖 機器人回報：目前已進入守候模式，等待明早開盤！")
    # ---------------------------------------------------------
    # 🧪 [模擬突破測試區] 
    # ---------------------------------------------------------
    print("🧪 正在進行 2313 模擬突破測試...", flush=True)
    
    # 1. 先手動給予 2313 一個低門檻的高點
    monitor_data["2313"] = {"high": 10.0, "low": 5.0, "triggered": False}
    
    # 2. 準備一個「模擬訊息」，設定現價為 15 (大於高點 10)
    mock_msg = {
        "event": "data",
        "resource": "stock.intraday.quote",
        "data": {
            "symbol": "2313",
            "lastPrice": 15.0
        }
    }
    
    # 3. 直接呼叫 handle_message 餵食這筆假資料
    handle_message(json.dumps(mock_msg))
    print("🧪 模擬測資發送完成，請檢查 Telegram 是否收到通知！", flush=True)
    # ---------------------------------------------------------

    print("🚀 StockCatcher 啟動中，等待數據...")
    stock.connect()

if __name__ == "__main__":
    main()