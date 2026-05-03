import os
import time
import requests
import urllib3
from datetime import datetime, timedelta, timezone, time as dtime
from typing import Dict, List, Any, Optional

# 🤫 隱藏 SSL 警告，保持日誌界面整潔
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ============================================================
# ⚙️ [系統配置區]
# ============================================================
class Config:
    # 🔐 金鑰管理：請務必透過 GitHub Secrets 設定環境變數
    FINMIND_TOKEN = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJ1c2VyX2lkIjoiRVNCMTc4MTMiLCJlbWFpbCI6Im0yOTk0MDUwOUBob3RtYWlsLmNvbSJ9.iGsA_PLkanve2aATgXU-RD2i7RKOHSLzMEmASMBOcDE" 
    FUGLE_API_KEY ="MzJiNjhmNjAtMzRjMy00OGZiLTg3YWQtMTJmMjg3NGE0MDNjIGJlNGVmY2Q2LTE5NDQtNDUzZi1iNTcxLTI5NmIzM2QwOTIzZQ=="
    TELEGRAM_TOKEN = "8480482512:AAGin83kwa61oa5F5rBj4NQMow-C9jsbJug"
    TELEGRAM_CHAT_ID = "1087480334"


    # 📈 策略監控參數
    VOL_EST_THRESHOLD = 1.6          # 預估量比門檻 (1.6x)
    STOP_LOSS_RATIO = 0.95           # 預設停損比率 (現價 -5%)
    POOL_REFRESH_INTERVAL = 1200     # 股池更新頻率 (每 20 分鐘更新一次熱門股)
    MAX_MONITOR_LIMIT = 100          # 同時監控上限 (上市+上櫃)
    API_THROTTLE_SLEEP = 1.2         # 節流時間 (確保 API 調用穩定)

    # ⏰ 策略關鍵時間點
    RECORD_END_TIME = dtime(9, 15)   # 3K 紀錄截止時間
    START_MONITOR_TIME = dtime(9, 16)# 策略觸發起始時間

    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

# 🏆 強化題材映射表：確保 2454, 2455, 2313 等核心標的題材完整
THEME_KEYWORDS = {
    "AI伺服器/零組件": ["廣達", "緯創", "技嘉", "英業達", "緯穎", "鴻海", "電腦及週邊設備業", "營邦", "勤誠", "南俊"],
    "半導體/IC設計": ["台積電", "聯發科", "世芯", "創意", "智原", "半導體業", "昇陽半導體", "聯電", "旺宏", "南亞科"],
    "CoWoS/先進封裝": ["弘塑", "辛耘", "萬潤", "均華", "志聖", "其他電子業"],
    "液冷/散熱模組": ["雙鴻", "奇鋐", "建準", "尼得科超眾", "晟銘電", "電子零組件業", "高力"],
    "矽光子/CPO": ["波若威", "上詮", "聯鈞", "光聖", "通信網路業", "華星光"],
    "低軌衛星/航太": ["華通", "昇達科", "啟碁", "耀華", "金像電", "元太", "邑錡", "全新", "2455", "2313"]
}

# 全域狀態記憶體
global_stock_info: Dict[str, Dict] = {} # 代號 -> {名稱, 產業}
stock_info_map: Dict[str, Any] = {}
monitor_data: Dict[str, Any] = {}

# ------------------------------------------------------------
# 🛠️ 工具函式 (Utils)
# ------------------------------------------------------------

def get_now_tw() -> datetime:
    """ 獲取台北標準時間 (UTC+8) """
    return datetime.now(timezone.utc) + timedelta(hours=8)

def get_passed_minutes() -> float:
    """ 計算開盤至今經過分鐘數 """
    now = get_now_tw()
    start = now.replace(hour=9, minute=0, second=0, microsecond=0)
    passed = (now - start).total_seconds() / 60
    return max(1, min(270, passed))

def fetch_yesterday_vol_finmind(symbol: str) -> int:
    """ 獲取昨日成交量作為基準量 """
    url = "https://api.finmindtrade.com/api/v4/data"
    params = {
        "dataset": "TaiwanStockPrice",
        "data_id": symbol,
        "start_date": (get_now_tw() - timedelta(days=10)).strftime('%Y-%m-%d'),
        "token": Config.FINMIND_TOKEN
    }
    try:
        res = requests.get(url, params=params, timeout=10).json()
        data = res.get('data', [])
        if len(data) >= 2:
            last_day = data[-2]
            vol = last_day.get('Trading_Volume') or last_day.get('trading_volume') or 0
            return int(vol) // 1000
    except: pass
    return 1000

def init_global_mapping():
    """ 啟動時建立全市場名冊，確保所有代號都能對應到名稱與族群 """
    print("📡 正在同步全市場基本資料名冊...", flush=True)
    url = "https://api.finmindtrade.com/api/v4/data"
    params = {"dataset": "TaiwanStockInfo", "token": Config.FINMIND_TOKEN}
    try:
        res = requests.get(url, params=params, timeout=15).json()
        for item in res.get('data', []):
            global_stock_info[item['stock_id']] = {
                'name': item['stock_name'],
                'industry': item['industry_category']
            }
        print(f"✅ 名冊同步完成，共計 {len(global_stock_info)} 檔標的。", flush=True)
    except Exception as e:
        print(f"❌ 名冊同步失敗: {e}", flush=True)

def get_theme_by_fuzzy(code: str) -> str:
    """ 根據名冊資訊進行題材匹配 """
    info = global_stock_info.get(code, {})
    name = info.get('name', '')
    industry = info.get('industry', '')
    search_str = name + industry
    for theme, keywords in THEME_KEYWORDS.items():
        if any(kw in search_str for kw in keywords): return theme
    return "熱門成交追蹤"

# ------------------------------------------------------------
# 📡 報價與通知模組
# ------------------------------------------------------------

def get_price_dual_engine(symbol: str) -> Optional[Dict[str, Any]]:
    """ 雙引擎行情獲取，包含模擬測試標的處理 """
    if "999" in symbol: return {"p": 125.0 if symbol=="9999" else 105.0, "v": 3000}
    try:
        f_url = f"https://api.fugle.tw/marketdata/v1.0/stock/intraday/quote/{symbol}"
        res = requests.get(f_url, headers={"X-API-KEY": Config.FUGLE_API_KEY.strip()}, timeout=8)
        if res.status_code == 200:
            d = res.json()
            return {"p": d.get('lastPrice'), "v": (d.get('total', {}).get('tradeVolume', 0)//1000)}
    except: pass
    return None

def send_tg_alert(stock_id: str, strategy: str, price: float, high: float, low: float, est_ratio: float, theme: str = "追蹤中"):
    """ 發送 Telegram 通知，包含停損點與 K 線連結 """
    code = stock_id.split(' ')[0]
    chart_url = f"https://www.fugle.tw/ai/{code}"
    stop_loss = round(price * Config.STOP_LOSS_RATIO, 2)
    
    header = "🔥【價量齊揚】" if "+" in strategy else "🚀【價格突破】" if "3K" in strategy else "📊【量能激增】"
    if "🧪" in strategy: header = "🧪【啟動測試】"

    msg = (
        f"{header}：{strategy}\n"
        f"━━━━━━━━━━━━━━\n"
        f"📈 *標的：* {stock_id}\n"
        f"💰 *觸發：* `{price}`\n"
        f"🛑 *停損：* `{stop_loss}`\n"
        f"🎯 *區間：* `{high}` (高) / `{low}` (低)\n"
        f"📊 *預估量比：* `{est_ratio}x`\n"
        f"💡 *題材：* {theme}\n"
        f"━━━━━━━━━━━━━━\n"
        f"🔗 [點此顯示目前 K 線圖]({chart_url})\n"
        f"⏰ {get_now_tw().strftime('%H:%M:%S')}"
    )
    try:
        url = f"https://api.telegram.org/bot{Config.TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": Config.TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"}, timeout=10)
    except: pass

# ------------------------------------------------------------
# 🏛️ 市場同步模組 (Dynamic Pool Engine)
# ------------------------------------------------------------

def sync_market_pool():
    """ 執行股池同步：抓取熱門標的並標註上市/上櫃 """
    tw_now = get_now_tw()
    print(f"\n🛰️ [{tw_now.strftime('%H:%M:%S')}] 執行股池動態同步...", flush=True)
    
    combined_pool = []
    # 1. 上市排行 (TWSE OpenAPI)
    try:
        res = requests.get("https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL", timeout=15, verify=False)
        if res.status_code == 200:
            for i in res.json():
                code = i.get('Code', '')
                if len(code) == 4:
                    combined_pool.append({'code': code, 'vol': int(i.get('TradeVolume', '0').replace(',', '') or 0) // 1000, 'm': '上市'})
    except: pass

    # 2. 上櫃排行 (FinMind 歷史回溯)
    fm_url = "https://api.finmindtrade.com/api/v4/data"
    for offset in range(8): # 增加回溯深度以跨過連假
        target_date = (tw_now - timedelta(days=offset)).strftime('%Y-%m-%d')
        params = {"dataset": "TaiwanStockPrice", "start_date": target_date, "token": Config.FINMIND_TOKEN}
        try:
            fm_res = requests.get(fm_url, params=params, timeout=15).json()
            if fm_res.get('data'):
                for item in fm_res['data']:
                    code = item.get('stock_id', '')
                    if len(code) == 4 and not any(x['code'] == code for x in combined_pool):
                        vol = item.get('Trading_Volume') or item.get('trading_volume') or 0
                        combined_pool.append({'code': code, 'vol': vol // 1000, 'm': '上櫃'})
                break 
        except: pass

    # 3. 建立監控資料，測試標的置頂
    top_list = sorted(combined_pool, key=lambda x: x['vol'], reverse=True)[:Config.MAX_MONITOR_LIMIT]
    test_stocks = [{'code': '9999', 'm': '測試', 'vol': 1000}, {'code': '9998', 'm': '測試', 'vol': 1000}]

    for item in (test_stocks + top_list):
        code = item['code']
        info = global_stock_info.get(code, {'name': '模擬測試', 'industry': item.get('m', '測試')})
        if code not in stock_info_map:
            y_vol = fetch_yesterday_vol_finmind(code) if "999" not in code else 1000
            stock_info_map[code] = {
                'name': info['name'], 
                'sector': info['industry'], 
                'market': item.get('m', '未知'), 
                'theme': get_theme_by_fuzzy(code)
            }
            monitor_data[code] = {
                "high": 110.0 if "999" in code else 0.0, 
                "low": 95.0 if "999" in code else 9999.0, 
                "y_vol": y_vol, 
                "trig_p": False, "trig_v": False, "trig_c": False
            }
    print(f"✅ 同步完成！目前股池：{len(stock_info_map)} 檔。", flush=True)

# ------------------------------------------------------------
# 🏁 主程式進入點 (Main Loop)
# ------------------------------------------------------------

def main():
    print("="*80, flush=True)
    print(f"🚀 偵察機啟動 | 蘇蘇的天機選股 | {get_now_tw().strftime('%Y-%m-%d %H:%M:%S')}", flush=True)
    print("="*80, flush=True)

    init_global_mapping()  # 1. 建立名冊
    sync_market_pool()     # 2. 初始同步

    # 啟動後發送一次通訊校準通知
    send_tg_alert("9999 系統測試", "🧪 偵察機啟動成功 (通訊校準)", 125.0, 110.0, 95.0, 3.0, "系統測試")
    
    last_sync_time = time.time()

    while True:
        tw_now = get_now_tw()
        now_time = tw_now.time()
        passed_min = get_passed_minutes()

        # 盤中定時更新股池 (核心問答回覆處)
        if time.time() - last_sync_time > Config.POOL_REFRESH_INTERVAL:
            sync_market_pool()
            last_sync_time = time.time()

        print(f"\n[掃描輪次: {tw_now.strftime('%H:%M:%S')}]", flush=True)
        print(f"{'代號名稱':<12} | {'市場':<4} | {'現價':<6} | {'量比':<5} | {'3K高':<6} | {'題材'}", flush=True)
        print("-" * 85, flush=True)

        for symbol in list(stock_info_map.keys()):
            info = stock_info_map[symbol]
            data = monitor_data[symbol]
            
            try:
                quote = get_price_dual_engine(symbol)
                if not quote or not quote['p']: continue

                lp, v = quote['p'], quote['v']
                est_ratio = round((v * (270 / passed_min)) / data['y_vol'], 2) if data['y_vol'] > 0 else 0
                
                # --- 🔥 3K 紀錄邏輯 (09:00 - 09:15) ---
                if now_time < Config.RECORD_END_TIME and "999" not in symbol:
                    if lp > data["high"]: data["high"] = lp
                    if lp < data["low"] or data["low"] == 9999.0: data["low"] = lp

                # --- 🚀 策略觸發判定 ---
                is_p_break = (lp > data['high'] > 0) and (now_time >= Config.START_MONITOR_TIME or "999" in symbol)
                is_v_surge = (est_ratio >= Config.VOL_EST_THRESHOLD)
                
                strat_title = ""
                if is_p_break and is_v_surge and not data["trig_c"]:
                    strat_title = "價量齊揚"; data["trig_c"] = True
                elif is_p_break and not data["trig_p"] and not data["trig_c"]:
                    strat_title = "3K突破"; data["trig_p"] = True
                elif is_v_surge and not data["trig_v"] and not data["trig_c"]:
                    strat_title = "量能激增"; data["trig_v"] = True

                # 日誌輸出
                display_name = f"{symbol} {info['name']}"
                print(f"{display_name:<12} | {info['market']:<4} | {lp:<8} | {est_ratio:<6} | {data['high']:<8} | {info['theme']}", flush=True)

                if strat_title:
                    send_tg_alert(display_name, strat_title, lp, data['high'], data['low'], est_ratio, info['theme'])

            except Exception as e:
                print(f"⚠️ {symbol} 掃描異常: {e}", flush=True)

            time.sleep(Config.API_THROTTLE_SLEEP)
        
        time.sleep(20)

if __name__ == "__main__":
    main()