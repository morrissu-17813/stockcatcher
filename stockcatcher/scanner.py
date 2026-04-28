import os
import time
import requests
import urllib3
import json
from datetime import datetime, timedelta, timezone, time as dtime

# 🤫 隱藏 SSL 警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ============================================================
# 🛠️ [核心金鑰填寫區]
# ============================================================
FINMIND_TOKEN = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJ1c2VyX2lkIjoiRVNCMTc4MTMiLCJlbWFpbCI6Im0yOTk0MDUwOUBob3RtYWlsLmNvbSJ9.iGsA_PLkanve2aATgXU-RD2i7RKOHSLzMEmASMBOcDE" 
FUGLE_API_KEY ="MzJiNjhmNjAtMzRjMy00OGZiLTg3YWQtMTJmMjg3NGE0MDNjIGJlNGVmY2Q2LTE5NDQtNDUzZi1iNTcxLTI5NmIzM2QwOTIzZQ=="
TELEGRAM_TOKEN = "8480482512:AAGin83kwa61oa5F5rBj4NQMow-C9jsbJug"
TELEGRAM_CHAT_ID = "1087480334"

# 策略門檻
VOL_EST_THRESHOLD = 1.8  # 預估全天成交量達昨日 1.8 倍視為異常量能
# ============================================================

# 2026 台股熱門題材完整映射表 (模糊比對引擎)
THEME_KEYWORDS = {
    "AI伺服器": ["廣達", "緯創", "技嘉", "英業達", "緯穎", "鴻海", "南俊國際", "勤誠", "營邦"],
    "CoWoS/先進封裝": ["台積電", "弘塑", "辛耘", "萬潤", "均華", "志聖", "惠特", "由田", "群創", "京元電子", "日月光"],
    "液冷/散熱": ["雙鴻", "奇鋐", "建準", "尼得科超眾", "晟銘電", "一詮", "高力", "泰碩", "協禧", "廣運"],
    "重電/強韌電網": ["中興電", "華城", "士電", "亞力", "大同", "東元", "樂事綠能", "華新", "大龍"],
    "機器人/自動化": ["所羅門", "廣明", "鴻準", "盟立", "羅昇", "穎漢", "昆盈", "和進", "直得"],
    "低軌衛星": ["華通", "昇達科", "啟碁", "耀華", "金像電", "台博", "元太", "敬鵬", "宏觀"],
    "矽光子/CPO": ["波若威", "上詮", "聯鈞", "光聖", "統新", "汎銓", "前鼎", "眾達-KY", "華星光"],
    "LPO題材": ["訊芯-KY", "上詮", "波若威", "聯鈞", "光聖", "前鼎", "台達電"],
    "RF題材": ["宏觀", "全新", "穩懋", "宏捷科", "耀登", "同欣電", "環宇-KY", "立積"],
    "半導體設備": ["家登", "帆宣", "京鼎", "漢唐", "亞翔", "聖暉", "均豪", "信紘科", "久元"],
    "ASIC/IP設計": ["世芯-KY", "創意", "智原", "M31", "金麗科", "神盾", "安國"],
    "無人機/軍工": ["雷虎", "中光電", "漢翔", "龍德造船", "全訊", "邑錡"],
    "航運/高股息": ["長榮", "陽明", "萬海", "新興", "裕民", "中航", "台航"]
}

stock_info_map = {}
monitor_data = {}

def get_now_tw():
    return datetime.now(timezone.utc) + timedelta(hours=8)

def get_passed_minutes():
    """ 計算開盤至今經過分鐘 (09:00 起算) """
    now = get_now_tw()
    start = now.replace(hour=9, minute=0, second=0, microsecond=0)
    passed = (now - start).total_seconds() / 60
    return max(1, min(270, passed))

def get_theme_by_fuzzy(code, name, sector):
    """ 模糊比對引擎：判斷題材標籤 """
    specific_map = {"2330": "AI晶片/半導體龍頭", "2317": "GB200/鴻海家族", "2313": "低軌衛星/PCB"}
    if code in specific_map: return specific_map[code]
    search_str = name + sector
    for theme, keywords in THEME_KEYWORDS.items():
        for kw in keywords:
            if kw in search_str: return theme
    return "熱門成交追蹤"

def send_tg_alert(stock_id, strategy, price, high, low, sector, theme, est_ratio):
    """ 豐富化 Telegram 通知 (三合一分流版) """
    symbol_only = stock_id.split(' ')[0]
    chart_url = f"https://www.fugle.tw/ai/{symbol_only}"
    
    # 標題 Emoji 判定
    if "+" in strategy: header, emoji = "🔥【價量齊揚】", "💥"
    elif "3K" in strategy: header, emoji = "🚀【策略觸發】", "📈"
    else: header, emoji = "📊【異常量能】", "⚡"

    msg = (
        f"{header}：{strategy}\n"
        f"━━━━━━━━━━━━━━\n"
        f"📈 *標的：* {stock_id}\n"
        f"💰 *現價：* `{price}`\n"
        f"🎯 *關鍵價：* `{high}`\n"
        f"🛑 *停損：* `{low}`\n"
        f"━━━━━━━━━━━━━━\n"
        f"📍 *族群：* {sector}\n"
        f"💡 *題材：* {theme}\n"
        f"📊 *預估量能：* `{est_ratio}x` (今日/昨日)\n"
        f"━━━━━━━━━━━━━━\n"
        f"🔗 [查看即時 K 線]({chart_url})\n"
        f"⏰ 台北時間：{get_now_tw().strftime('%H:%M:%S')}"
    )
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"}, timeout=10)
    except: pass

def fetch_top_50_fully_augmented():
    """ 獲取 50 檔熱門股並結合 FinMind 族群與題材 """
    print(f"\n🏛️ [{get_now_tw().strftime('%H:%M:%S')}] 正在獲取證交所與 FinMind 數據...", flush=True)
    twse_url = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
    fm_info_url = "https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockInfo"
    
    try:
        p_res = requests.get(twse_url, verify=False, timeout=20)
        f_res = requests.get(fm_info_url, timeout=20)
        
        if p_res.status_code == 200:
            prices = p_res.json()
            # 建立 FinMind 族群地圖
            fm_sectors = {i['stock_id']: i['industry_category'] for i in f_res.json().get('data', [])} if f_res.status_code == 200 else {}
            
            processed = []
            for item in prices:
                code = item.get('Code', '')
                if len(code) == 4:
                    vol_raw = item.get('TradeVolume', '0').replace(',', '')
                    vol = int(vol_raw) // 1000 if vol_raw else 0 # 轉為張
                    if vol > 0:
                        name = item.get('Name', '')
                        sector = fm_sectors.get(code, "一般個股")
                        processed.append({
                            'code': code, 'name': name, 'sector': sector,
                            'total_vol': vol, 'price': item.get('ClosingPrice', '0'),
                            'theme': get_theme_by_fuzzy(code, name, sector)
                        })
            # 按成交量排名前 50
            return sorted(processed, key=lambda x: x['total_vol'], reverse=True)[:50]
    except Exception as e:
        print(f"💥 資料獲取失敗: {e}", flush=True)
    return []

def get_price_dual_engine(symbol):
    """ 雙引擎報價 (Fugle/FinMind) """
    try:
        f_url = f"https://api.fugle.tw/marketdata/v1.0/stock/intraday/quote/{symbol}"
        f_res = requests.get(f_url, headers={"X-API-KEY": FUGLE_API_KEY.strip()}, timeout=8)
        if f_res.status_code == 200:
            d = f_res.json()
            return {"p": d.get('lastPrice'), "v": (d.get('total', {}).get('tradeVolume', 0)//1000), "src": "Fugle"}
    except: pass
    try:
        fm_url = "https://api.finmindtrade.com/api/v4/data"
        params = {"dataset": "TaiwanStockPrice", "data_id": symbol, "start_date": get_now_tw().strftime('%Y-%m-%d'), "token": FINMIND_TOKEN}
        fm_res = requests.get(fm_url, params=params, timeout=8)
        fm_d = fm_res.json().get('data', [])
        if fm_d:
            last = fm_d[-1]
            return {"p": last.get('close'), "v": last.get('trading_volume', 0), "src": "FinMind"}
    except: pass
    return None

def main():
    print("="*80, flush=True)
    print(f"🚀 偵察機 [價量三合一精進版] 啟動 | {get_now_tw().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*80, flush=True)
    
    top_50 = fetch_top_50_fully_augmented()
    
    # 初始化測試資料與正式名單
    monitor_list = {
        "9999": {'name': '3K突破測試', 'sector': '測試族群', 'theme': '邏輯驗證', 'total_vol': 1000},
        "9998": {'name': '量能異常測試', 'sector': '測試族群', 'theme': '量能驗證', 'total_vol': 1000},
        "9997": {'name': '價量齊揚測試', 'sector': '測試族群', 'theme': '完全體驗證', 'total_vol': 1000}
    }
    for s in top_50: monitor_list[s['code']] = s

    for symbol, info in monitor_list.items():
        stock_info_map[symbol] = info
        monitor_data[symbol] = {
            "high": 110.0 if "999" in symbol else 0.0, 
            "low": 95.0 if "999" in symbol else 9999.0, 
            "y_vol": info['total_vol'],
            "trig_p": False, "trig_v": False, "trig_c": False
        }

    print(f"📊 [GitHub 監控報表] 已載入 {len(monitor_list)} 檔標的 (含族群與題材)\n", flush=True)

    while True:
        tw_now = get_now_tw()
        now_time = tw_now.time()
        passed_min = get_passed_minutes()
        
        status = "【紀錄高低點】" if now_time < dtime(9, 15) else "【突破監控中】"
        print(f"\n⏰ --- 輪詢開始: {tw_now.strftime('%H:%M:%S')} {status} ---", flush=True)
        print(f"{'代號':<5} | {'股名':<8} | {'現價':<6} | {'預估量比':<6} | {'3K高':<6} | {'族群'}", flush=True)
        print("-" * 85, flush=True)

        for symbol in list(stock_info_map.keys()):
            info = stock_info_map[symbol]
            data = monitor_data[symbol]
            
            # 報價獲取 (含測試模擬)
            if symbol == "9999": res = {"p": 125.0, "v": 1100, "src": "Mock"} # 僅價過
            elif symbol == "9998": res = {"p": 105.0, "v": 2500, "src": "Mock"} # 僅量過
            elif symbol == "9997": res = {"p": 130.0, "v": 3000, "src": "Mock"} # 價量齊過
            else: res = get_price_dual_engine(symbol)
            
            if res and res['p']:
                lp, v = res['p'], res['v']
                # 計算預估量比
                est_ratio = round((v * (270 / passed_min)) / data['y_vol'], 2) if data['y_vol'] > 0 else 0
                
                print(f"{symbol:<5} | {info['name']:<8} | {lp:<6} | {est_ratio:<8} | {data['high']:<6} | {info['sector']}", flush=True)

                # 策略判斷旗標
                is_p_break = (lp > data['high'] > 0) or (symbol in ["9999", "9997"])
                is_v_break = (est_ratio >= VOL_EST_THRESHOLD) or (symbol in ["9998", "9997"])
                
                # 09:15 前更新區間高低 (排除測試股)
                if now_time < dtime(9, 15) and "999" not in symbol:
                    if lp > data["high"]: data["high"] = lp
                    if lp < data["low"] or data["low"] == 9999.0: data["low"] = lp
                
                # 09:16 後或測試股執行通知
                elif (now_time >= dtime(9, 16)) or ("999" in symbol):
                    strat = ""
                    # A. 雙重觸發
                    if is_p_break and is_v_break and not data["trig_c"]:
                        strat = "3K突破 + 異常量能"
                        data["trig_c"] = data["trig_p"] = data["trig_v"] = True
                    # B. 僅價突破
                    elif is_p_break and not data["trig_p"] and not data["trig_c"]:
                        strat = "盤中 3K 多頭突破"
                        data["trig_p"] = True
                    # C. 僅量異常
                    elif is_v_break and not data["trig_v"] and not data["trig_c"]:
                        strat = "盤中量能異常湧現"
                        data["trig_v"] = True
                    
                    if strat:
                        send_tg_alert(f"{symbol} {info['name']}", strat, lp, data['high'], data['low'], 
                                      sector=info['sector'], theme=info['theme'], est_ratio=est_ratio)

            time.sleep(1.2) # API 節流
        
        print(f"✅ 輪巡結束，等待下一輪...", flush=True)
        time.sleep(20)

if __name__ == "__main__":
    main()