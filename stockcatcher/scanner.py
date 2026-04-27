import os
import time
import requests
import urllib3
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
# ============================================================

stock_info_map = {}
monitor_data = {}

def get_now_tw():
    """ 獲取台北時間 """
    return datetime.now(timezone.utc) + timedelta(hours=8)

def send_tg_alert(stock_id, trend, price, high, low, sector="N/A", theme="核心監控", vol_info=""):
    """ 豐富化 Telegram 通知 """
    symbol_only = stock_id.split(' ')[0]
    chart_url = f"https://www.fugle.tw/ai/{symbol_only}"
    header = "💥【異常量能】" if "量能" in trend else "🚀【策略觸發】"
    
    msg = (
        f"{header}：{trend}\n"
        f"━━━━━━━━━━━━━━\n"
        f"📈 *標的：* {stock_id}\n"
        f"💰 *現價：* `{price}`\n"
        f"🎯 *關鍵價：* `{high}`\n"
        f"🛑 *建議停損：* `{low}`\n"
        f"━━━━━━━━━━━━━━\n"
        f"📍 *族群：* {sector} | 💡 *題材：* {theme}\n"
        f"📊 *量能：* {vol_info}\n"
        f"━━━━━━━━━━━━━━\n"
        f"🔗 [查看富果即時 K 線]({chart_url})\n"
        f"⏰ 台北時間：{get_now_tw().strftime('%H:%M:%S')}"
    )
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"}, timeout=10)
    except: pass

def fetch_top_50_from_twse():
    """ 從證交所 OpenAPI 獲取成交排行前 50 檔 """
    print(f"\n🏛️ [{get_now_tw().strftime('%H:%M:%S')}] 正在獲取證交所熱門名單...", flush=True)
    url = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
    s_url = "https://openapi.twse.com.tw/v1/opendata/t187ap03_P"
    try:
        p_res = requests.get(url, verify=False, timeout=20)
        s_res = requests.get(s_url, verify=False, timeout=20)
        if p_res.status_code == 200:
            prices = p_res.json()
            sectors = {i['公司代號']: i['產業別'] for i in s_res.json()} if s_res.status_code == 200 else {}
            processed = []
            for item in prices:
                code = item.get('Code', '')
                if len(code) == 4:
                    vol_raw = item.get('TradeVolume', '0').replace(',', '')
                    vol = int(vol_raw) // 1000 if vol_raw else 0
                    processed.append({
                        'code': code, 'name': item.get('Name', ''),
                        'sector': sectors.get(code, "一般股"),
                        'avg_vol_min': max(1, vol // 270), 'total_vol': vol
                    })
            return sorted(processed, key=lambda x: x['total_vol'], reverse=True)[:50]
    except Exception as e:
        print(f"💥 證交所 API 連線失敗: {e}", flush=True)
    
    # 🛡️ 保底名單
    backup_codes = ["2313", "2330", "2317", "2454", "2303", "2603", "2609", "3231", "2382", "2618"]
    return [{'code': c, 'name': f'監控_{c}', 'sector': '核心監控', 'avg_vol_min': 50} for c in backup_codes]

def get_price_dual_engine(symbol):
    """ 雙引擎報價 (Fugle 優先, FinMind 備援) """
    # 1. 富果引擎
    try:
        f_url = f"https://api.fugle.tw/marketdata/v1.0/stock/intraday/quote/{symbol}"
        f_res = requests.get(f_url, headers={"X-API-KEY": FUGLE_API_KEY.strip()}, timeout=8)
        if f_res.status_code == 200:
            d = f_res.json()
            return {"p": d.get('lastPrice'), "v": (d.get('total', {}).get('tradeVolume', 0)//1000), "src": "Fugle"}
    except: pass

    # 2. FinMind 引擎 (備援)
    try:
        fm_url = "https://api.finmindtrade.com/api/v4/data"
        params = {"dataset": "TaiwanStockPrice", "data_id": symbol, "start_date": get_now_tw().strftime('%Y-%m-%d'), "token": FINMIND_TOKEN}
        fm_res = requests.get(fm_url, params=params, timeout=8)
        if fm_res.status_code == 200:
            fm_d = fm_res.json().get('data', [])
            if fm_d:
                last = fm_d[-1]
                return {"p": last.get('close'), "v": last.get('trading_volume', 0), "src": "FinMind"}
    except: pass
    return None

def main():
    print("="*80, flush=True)
    print(f"🚀 偵察機 [重裝版] 啟動 | 台北時間: {get_now_tw().strftime('%Y-%m-%d %H:%M:%S')}", flush=True)
    print("="*80, flush=True)
    
    raw_list = fetch_top_50_from_twse()
    monitor_list = {
        "9999": {'name': '突破測試', 'sector': '測試', 'avg_vol_min': 10},
        "9998": {'name': '爆量測試', 'sector': '測試', 'avg_vol_min': 10}
    }
    for s in raw_list: monitor_list[s['code']] = s

    for symbol, info in monitor_list.items():
        stock_info_map[symbol] = info
        monitor_data[symbol] = {"high": 110.0 if symbol=="9999" else 0.0, "low": 95.0 if symbol=="9999" else 9999.0, "last_v": 0, "trig_3k": False, "trig_vol": False}

    print(f"📊 監控清單就緒，共 {len(monitor_list)} 檔標的。\n", flush=True)

    while True:
        tw_now = get_now_tw()
        now_time = tw_now.time()
        
        # 測試時設為 True；正式上線可改回交易時間判定
        if True: 
            status = "【紀錄中】" if now_time < dtime(9, 15) else "【監控中】"
            print(f"\n⏰ --- 輪詢開始: {tw_now.strftime('%H:%M:%S')} {status} ---", flush=True)
            print(f"{'代號':<5} | {'股名':<8} | {'現價':<6} | {'分盤量':<5} | {'3K高':<6} | {'來源'}", flush=True)
            print("-" * 75, flush=True)

            for symbol in list(stock_info_map.keys()):
                info = stock_info_map[symbol]
                data = monitor_data[symbol]
                
                # 獲取報價 (含測試案例)
                if symbol == "9999": res = {"p": 125.0, "v": 1000, "src": "Mock"}
                elif symbol == "9998": res = {"p": 105.0, "v": 5500, "src": "Mock"}
                else: res = get_price_dual_engine(symbol)
                
                if res and res['p']:
                    lp, v, src = res['p'], res['v'], res['src']
                    if data["last_v"] == 0: data["last_v"] = v
                    ivol = v - data["last_v"]
                    
                    # 異常量判定
                    avg_v = info.get('avg_vol_min', 1)
                    is_spike = (ivol > (avg_v * 5) and ivol > 100) or (symbol == "9998")
                    
                    state = "🔥" if is_spike else "📈" if data["trig_3k"] else "  "
                    print(f"{symbol:<5} | {info['name']:<8} | {lp:<6} | {ivol:<5} | {data['high']:<6} | {src:<8} {state}", flush=True)

                    # 通知邏輯
                    if is_spike and not data["trig_vol"]:
                        send_tg_alert(f"{symbol} {info['name']}", "盤中異常量能湧現", lp, data['high'], data['low'], 
                                      sector=info['sector'], vol_info=f"瞬間增量 {ivol} 張")
                        data["trig_vol"] = True

                    if now_time < dtime(9, 15) and symbol not in ["9999", "9998"]:
                        if lp > data["high"]: data["high"] = lp
                        if lp < data["low"] or data["low"] == 9999.0: data["low"] = lp
                    elif not data["trig_3k"] and (data["high"] > 0 or symbol == "9999"):
                        if lp > data["high"] or symbol == "9999":
                            send_tg_alert(f"{symbol} {info['name']}", "盤中 3K 多頭突破", lp, data["high"], data["low"], 
                                          sector=info['sector'], vol_info=f"當前成交 {v} 張")
                            data["trig_3k"] = True
                    data["last_v"] = v
                time.sleep(1.2) # API 節流
            
            print(f"✅ 輪巡結束，等待 20 秒...", flush=True)
            time.sleep(20)
        else:
            time.sleep(60)

if __name__ == "__main__":
    main()