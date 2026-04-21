import os
import json
import time
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
    print("🔍 正在偵測今日盤中強勢熱門股...")
    rest_client = RestClient(api_key=api_key)
    
    try:
        # 正確的拼字：rankings
        rankings = rest_client.stock.intraday.rankings(type='volumes')
        candidates = [item['symbol'] for item in rankings][:50]
        print(f"📈 成功取得熱門股清單 (共 {len(candidates)} 檔)")
    except Exception as e:
        print(f"⚠️ 無法取得即時排行 ({e})，切換至備用清單...")
        candidates = ["2330", "2455", "2313", "5222", "6568", "2303", "2382", "3231"]

    mapping = {}
    print("📦 正在下載個股基本面資料...")
    for symbol in candidates:
        try:
            meta = rest_client.stock.intraday.meta(symbol=symbol)
            # 更加穩健的名稱抓取
            name = meta.get("nameZh") or meta.get("name") or symbol
            mapping[symbol] = {
                "name": name,
                "industry": meta.get("industryZh") or "其他",
                "themes": "量能激增強勢股"
            }
            time.sleep(0.05) 
        except:
            mapping[symbol] = {"name": symbol, "industry": "未知", "themes": "監控中"}

    # 這裡會印出名稱，讓你確認有沒有抓到中文
    print(f"✅ 初始化完成！目前監控：{', '.join([m['name'] for m in mapping.values()][:5])} ...")
    return mapping
    """
    自動化清單功能：
    1. 優先從富果 API 抓取今日成交量前 50 大熱門股。
    2. 自動抓取每隻個股的中文名稱與產業分類。
    3. 若 API 失敗則自動啟用備援名單，確保系統不中斷。
    """
    print("🔍 正在偵測今日盤中強勢熱門股...")
    rest_client = RestClient(api_key=api_key)
    
    # --- 步驟 1：抓取熱門清單 ---
    try:
        # 修正拼字：rankings (原本多了一個 s)
        rankings = rest_client.stock.intraday.rankings(type='volumes')
        candidates = [item['symbol'] for item in rankings][:50]
        print(f"📈 成功從富果 API 取得最新熱門股清單 (共 {len(candidates)} 檔)")
    except Exception as e:
        print(f"⚠️ 無法取得即時排行 ({e})，切換至備用候選名單...")
        # 備用名單 (涵蓋權值與熱門股)
        candidates = [
            "2455", "2317", "5222", "6568", "2609", "2303", "2382", "3231", 
            "2357", "2881", "2882", "1605", "2618", "2610", "1513", "1519"
        ]

    # --- 步驟 2：抓取詳細個股資訊 (名稱與產業) ---
    mapping = {}
    print("📦 正在下載個股基本面資料 (名稱、產業)...")
    
    for symbol in candidates:
        try:
            # 取得個股元數據 (Meta)
            meta = rest_client.stock.intraday.meta(symbol=symbol)
            
            # 強化名稱抓取邏輯，確保中文能正常顯示
            # 優先取 nameZh (繁體中文)，若無則取 name，最後才用代號
            name = meta.get("nameZh") or meta.get("name") or symbol
            industry = meta.get("industryZh") or "其他"
            
            mapping[symbol] = {
                "name": name,
                "industry": industry,
                "themes": "量能激增強勢股" # 這裡可以固定，或未來擴充
            }
            
            # 💡 蘇蘇的小撇步：在循環中加入微小停頓 (0.05秒)，防止被 API 伺服器誤認成攻擊
            time.sleep(0.05) 
            
        except Exception as e:
            # 如果單一標的抓取失敗，保留代號繼續執行，不讓整台車停下來
            mapping[symbol] = {
                "name": symbol, 
                "industry": "未知", 
                "themes": "動態監控標的"
            }
            continue

    # 取得前 5 檔作為預覽顯示在螢幕上
    names_preview = [m['name'] for m in mapping.values()][:5]
    print(f"✅ 初始化完成！目前監控：{', '.join(names_preview)} ...等 {len(mapping)} 檔")
    
    return mapping
    """
    優先從富果 API 抓取成交量排行，失敗時才使用備用名單。
    """
    print("🔍 正在偵測今日盤中強勢熱門股...")
    rest_client = RestClient(api_key=api_key)
    
    # 1. 嘗試抓取「成交量排行」 (Volumes Ranking)
    try:
        # 抓取前 50 檔熱門股 (免費版建議先從 50 檔開始，比較穩定)
        # 註：富果 API rankings 參數：type='volumes' 代表成交量
        rankings = rest_client.stock.intraday.rankings(type='volumes')
        candidates = [item['symbol'] for item in rankings][:50] 
        print(f"📈 成功從 API 取得最新熱門股清單 (前 {len(candidates)} 檔)")
    except Exception as e:
        print(f"⚠️ 無法取得即時排行 ({e})，切換至備用候選名單...")
        # 備用名單 (Fallback List)
        candidates = [
            "2330", "2455", "6568", "5222", "2609", "2303", "2382", "3231", 
            "2357", "2881", "2882", "1605", "2618", "2610", "1513", "1519"
        ]

    # 2. 抓取這 50 檔股票的詳細資訊 (名稱、產業)
    mapping = {}
    print("📦 正在下載個股基本面資料...")
    
    for symbol in candidates:
        try:
            # 取得個股元數據 (Meta)
            meta = rest_client.stock.intraday.meta(symbol=symbol)
            mapping[symbol] = {
                "name": meta.get("nameZh", symbol),
                "industry": meta.get("industryZh", "其他"),
                "themes": "量能激增強勢股" # 這裡可以根據排行類型動態修改
            }
            # 稍微停頓避免被富果伺服器阻擋 (Rate Limit)
            time.sleep(0.05) 
        except Exception as e:
            mapping[symbol] = {"name": symbol, "industry": "未知", "themes": "動態監控"}
            continue

    print(f"✅ 初始化完成！目前監控：{', '.join([m['name'] for m in mapping.values()][:5])} ...等 {len(mapping)} 檔")
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