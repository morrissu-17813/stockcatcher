import os
import time
import requests
import urllib3
import pandas as pd
from datetime import datetime, timedelta, timezone, time as dtime
from typing import Dict, List, Any, Set

# 🤫 隱藏 SSL 警告，保持 Console 輸出專業
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ============================================================
# ⚙️ [系統配置區]
# ============================================================
class Config:
    # 🔐 憑證管理：請透過環境變數注入，嚴禁 Hardcode
    FINMIND_TOKEN = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJ1c2VyX2lkIjoiRVNCMTc4MTMiLCJlbWFpbCI6Im0yOTk0MDUwOUBob3RtYWlsLmNvbSJ9.iGsA_PLkanve2aATgXU-RD2i7RKOHSLzMEmASMBOcDE" 
    FUGLE_API_KEY ="MzJiNjhmNjAtMzRjMy00OGZiLTg3YWQtMTJmMjg3NGE0MDNjIGJlNGVmY2Q2LTE5NDQtNDUzZi1iNTcxLTI5NmIzM2QwOTIzZQ=="
    TELEGRAM_TOKEN = "8480482512:AAGin83kwa61oa5F5rBj4NQMow-C9jsbJug"
    TELEGRAM_CHAT_ID = "-1003613268841"

    # 🛠️ [測試模式] True 時允許非交易時段模擬資料
    TEST_MODE = True 

    # 📈 選股池配額 [90 上市 : 30 上櫃 : 20 權證標的]
    TSE_QUOTA = 90
    OTC_QUOTA = 30
    WARRANT_QUOTA = 20
    OTC_VOL_THRESHOLD = 500 # 💡 上櫃成交量硬性門檻 (張)

    # 🎯 策略參數
    VOL_EST_THRESHOLD = 1.6 
    STOP_LOSS_RATIO = 0.95  
    
    # ⏰ 時間控制點
    MARKET_OPEN = dtime(9, 0)
    RECOVERY_THRESHOLD = dtime(9, 15) 
    MARKET_CLOSE = dtime(13, 35)
    
    # 🏎️ 效能控制
    API_THROTTLE_SLEEP = 1.2    # 標的間隔 (1.2s)
    ROUND_INTERVAL_SLEEP = 10   # 💡 每一輪掃描結束後休眠時間 (10s)

# 全域狀態記憶體
global_stock_info = {} 
stock_info_map = {}     
monitor_data = {}       
warrant_target_list = set()

# ------------------------------------------------------------
# 🛠️ 蘇蘇的防禦性工具函式 (Safety Utilities)
# ------------------------------------------------------------

def safe_cast(val: Any, to_type: type, default: Any = 0) -> Any:
    """ 解決轉型崩潰，確保 API 回傳資料型態安全 """
    try:
        if val is None or str(val).strip() == "": return default
        return to_type(float(str(val).replace(',', '').strip()))
    except: return default

def get_now_tw() -> datetime:
    """ 獲取台北標準時間 (UTC+8) """
    return datetime.now(timezone.utc) + timedelta(hours=8)

def is_valid_stock(sid: str, info: dict) -> bool:
    """ 💡 強力過濾器：排除金融股與 ETF """
    sid_str = str(sid)
    if len(sid_str) != 4 or sid_str.startswith("00"): return False
    # 產業別檢查
    industry = info.get('industry', '')
    if any(k in industry for k in ["金融", "保險"]): return False 
    return True

# ------------------------------------------------------------
# 🏛️ 資料採集與修復模組 (Data Pipeline)
# ------------------------------------------------------------

def api_get_json(url: str) -> Any:
    """ 安全的 API 請求封裝，防止 Expecting value 報錯 """
    try:
        res = requests.get(url, verify=False, timeout=10)
        if res.status_code == 200 and 'application/json' in res.headers.get('Content-Type', ''):
            return res.json()
    except: pass
    return None

def init_global_mapping():
    """ 同步名冊：建立產業別與名稱資料庫 """
    print("📡 正在同步全市場名冊 (FinMind)...", flush=True)
    url = f"https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockInfo&token={Config.FINMIND_TOKEN}"
    data = api_get_json(url)
    if data:
        for item in data.get('data', []):
            global_stock_info[str(item['stock_id'])] = {
                'name': item['stock_name'], 'industry': item['industry_category']
            }
        print(f"✅ 名冊同步完成，共計 {len(global_stock_info)} 檔標的。", flush=True)

def load_official_warrant_targets():
    """ 💡 從官方來源獲取 20 檔不重複權證熱門標的 """
    print("📡 正在獲取官方熱門權證標的快照...", flush=True)
    temp_warrant_map = {}
    
    t_data = api_get_json("https://openapi.twse.com.tw/v1/exchangeReport/TWT48U_ALL")
    o_data = api_get_json("https://www.tpex.org.tw/openapi/v1/tpex_mainboard_warrant_quotes")
    
    for source in [t_data, o_data]:
        if source:
            for i in source:
                underlying = i.get('UnderlyingIdentifier', '').strip()
                vol = safe_cast(i.get('TradeVolume'), int)
                if len(underlying) == 4:
                    temp_warrant_map[underlying] = temp_warrant_map.get(underlying, 0) + vol

    sorted_warrants = sorted(temp_warrant_map.items(), key=lambda x: x[1], reverse=True)
    for sid, _ in sorted_warrants:
        if is_valid_stock(sid, global_stock_info.get(sid, {})):
            warrant_target_list.add(sid)
        if len(warrant_target_list) >= Config.WARRANT_QUOTA: break
            
    # 💡 保底機制：防止半夜資料為空 (Warrant Quota Check)
    if len(warrant_target_list) < Config.WARRANT_QUOTA:
        backup = ["2330", "2317", "2454", "2308", "3017", "3231", "2382", "6669", "3037", "2357", 
                  "1513", "1519", "2603", "2609", "2455", "2313", "3034", "8046", "3711"]
        for s in backup:
            if len(warrant_target_list) < Config.WARRANT_QUOTA: warrant_target_list.add(s)
    print(f"✅ 權證池載入完成: {len(warrant_target_list)} 檔。", flush=True)

def sync_market_pool():
    """ 💡 分流同步：上櫃量能 500 張硬性篩選與金融股排除 """
    print(f"🛰️ [{get_now_tw().strftime('%H:%M:%S')}] 啟動配額同步程序...", flush=True)
    tse_raw, otc_raw = [], []

    # 1. 上市 (TSE)
    t_data = api_get_json("https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL")
    if t_data:
        for i in t_data:
            sid = i.get('Code')
            if is_valid_stock(sid, global_stock_info.get(sid, {})):
                vol = safe_cast(i.get('TradeVolume'), int) // 1000 # 股轉張
                tse_raw.append({'code': sid, 'vol': vol, 'market': '上市'})

    # 2. 上櫃 (OTC) - 💡 加入 500 張硬過濾
    o_data = api_get_json("https://www.tpex.org.tw/openapi/v1/tpex_mainboard_quotes")
    if o_data:
        for i in o_data:
            sid = i.get('SecuritiesCompanyCode', '').strip()
            if is_valid_stock(sid, global_stock_info.get(sid, {})):
                vol = safe_cast(i.get('TradingVolume'), int) // 1000
                # 💡 只保留成交量 >= 500 張的標的
                if vol >= Config.OTC_VOL_THRESHOLD:
                    otc_raw.append({'code': sid, 'vol': vol, 'market': '上櫃'})
    
    top_tse = sorted(tse_raw, key=lambda x: x['vol'], reverse=True)[:Config.TSE_QUOTA]
    top_otc = sorted(otc_raw, key=lambda x: x['vol'], reverse=True)[:Config.OTC_QUOTA]
    
    # 上櫃保底 (深夜 API 資料缺失時啟動)
    if len(top_otc) == 0 and Config.TEST_MODE:
        backup_otc = ["8069", "5483", "6488", "3105", "3293", "6274", "3529", "5347", "8299"]
        for s in backup_otc:
            if len(top_otc) < Config.OTC_QUOTA:
                top_otc.append({'code': s, 'vol': 501, 'market': '上櫃'})

    print(f"📊 [同步檢查] 上市: {len(top_tse)} 檔 | 上櫃: {len(top_otc)} 檔 | 權證: {len(warrant_target_list)} 檔", flush=True)
    
    # 建立總監控清單
    all_final_list = [{'code': s, 'vol': 1000, 'market': '權證'} for s in list(warrant_target_list)]
    all_final_list += top_tse + top_otc

    for item in all_final_list:
        code = item['code']
        if code not in stock_info_map:
            info = global_stock_info.get(code, {'name': '搜尋中', 'industry': '熱門成交'})
            stock_info_map[code] = {'name': info['name'], 'market': item['market'], 'industry': info['industry']}
            monitor_data[code] = {"high": 0.0, "low": 9999.0, "y_vol": item['vol'], "trig": False}

# ------------------------------------------------------------
# 📡 警報與通訊 (Alert Engine)
# ------------------------------------------------------------

def send_tg_alert(sid: str, strategy: str, lp: float, high: float, low: float, ratio: float):
    """ 💡 格式化 Telegram 通知：包含 3K 高低點、正式 nstock 連結、產業別 """
    info = stock_info_map.get(sid, {'name': '測試標的', 'industry': '系統測試'})
    # 💡 修正後的連結格式
    nstock_url = f"https://www.nstock.tw/stock_info?stock_id={sid}"
    header = "🚨【啟動測試】" if "測試" in strategy else "🔥【價量齊揚】"

    msg = (
        f"{header} {strategy}\n"
        f"━━━━━━━━━━━━━━\n"
        f"📈 *標的：* `{sid}` **{info['name']}**\n"
        f"💰 *現價：* `{lp}`\n"
        f"🎯 *3K高：* `{high}` | 🛡️ *3K低：* `{low}`\n"
        f"📊 *預估量比：* `{ratio}x`\n"
        f"🏷️ *產業別：* {info['industry']}\n"
        f"━━━━━━━━━━━━━━\n"
        f"🔗 [nstock 完整數據]({nstock_url})\n"
        f"⏰ {get_now_tw().strftime('%H:%M:%S')}"
    )
    try:
        url = f"https://api.telegram.org/bot{Config.TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": Config.TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"}, timeout=10)
    except: pass

# ------------------------------------------------------------
# 💹 執行模組 (Execution)
# ------------------------------------------------------------

def recover_3k_data(target_list: List[str]):
    """ 3K 高低點補課：透過 Fugle Candles API 追溯 """
    print(f"🔄 正在為 {len(target_list)} 檔標的高低點執行 3K 補課...", flush=True)
    for sid in target_list:
        try:
            url = f"https://api.fugle.tw/marketdata/v1.0/stock/intraday/candles/{sid}"
            res = requests.get(url, headers={"X-API-KEY": Config.FUGLE_API_KEY.strip()}, timeout=10).json()
            candles = res.get('candles', [])
            # 過濾 09:15 前數據
            v_highs = [c['high'] for c in candles if c['time'].split('T')[1][:5] <= "09:15"]
            v_lows = [c['low'] for c in candles if c['time'].split('T')[1][:5] <= "09:15"]
            if v_highs:
                monitor_data[sid]['high'] = max(v_highs)
                monitor_data[sid]['low'] = min(v_lows)
        except: pass

def main():
    print("="*90)
    print(f"🛡️ 偵察機升空 | V26.0 | {get_now_tw().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*90, flush=True)

    # 1. 系統初始化
    init_global_mapping() 
    load_official_warrant_targets() 
    sync_market_pool()
    
    # 2. 💡 啟動即測試：驗證資料呈現與通訊連結
    send_tg_alert("2330", "啟動與 3K 突破通道驗證", 1000.0, 990.0, 970.0, 2.5)

    # 3. 補課判定 (09:15 後啟動執行)
    now_time = get_now_tw().time()
    if now_time > Config.RECOVERY_THRESHOLD:
        recover_3k_data(list(stock_info_map.keys()))

    while True:
        tw_now = get_now_tw()
        if not Config.TEST_MODE and not (Config.MARKET_OPEN <= tw_now.time() <= Config.MARKET_CLOSE):
            print(f"💤 非交易時段...", end='\r')
            time.sleep(10); continue

        # 看板標題
        print(f"\n[掃描週期: {tw_now.strftime('%H:%M:%S')}]")
        print(f"{'代號名稱':<12} | {'市場':<4} | {'現價':<8} | {'量比':<6} | {'3K高':<8} | {'3K低':<8}")
        print("-" * 88)

        # passed_min 計算
        diff = (datetime.combine(tw_now.date(), tw_now.time()) - datetime.combine(tw_now.date(), dtime(9,0))).total_seconds() / 60
        passed_min = max(1, min(270, diff))

        for sid in list(stock_info_map.keys()):
            info, data = stock_info_map[sid], monitor_data[sid]
            try:
                # 調用行情 API
                f_url = f"https://api.fugle.tw/marketdata/v1.0/stock/intraday/quote/{sid}"
                res = requests.get(f_url, headers={"X-API-KEY": Config.FUGLE_API_KEY.strip()}, timeout=5).json()
                lp = res.get('lastPrice')
                v = safe_cast(res.get('total', {}).get('tradeVolume'), int) // 1000
                
                # 測試模式模擬
                if lp is None and Config.TEST_MODE: lp, v = 105.0, 500
                if not lp: continue
                
                # 💡 盤中錄製程序 (09:15 前)
                if tw_now.time() <= Config.RECOVERY_THRESHOLD:
                    if lp > data['high']: data['high'] = lp
                    if lp < data['low'] or data['low'] == 9999.0: data['low'] = lp
                
                ratio = round((v * (270 / passed_min)) / data['y_vol'], 2) if data['y_vol'] > 0 else 0
                
                # 控制台輸出
                print(f"{sid} {info['name']:<8} | {info['market']:<4} | {lp:<8} | {ratio:<6} | {data['high']:<8} | {data['low']:<8}")

                # 策略觸發
                if lp > data['high'] > 0 and ratio >= Config.VOL_EST_THRESHOLD and not data['trig']:
                    send_tg_alert(sid, "3K突破偵測", lp, data['high'], data['low'], ratio)
                    data['trig'] = True

            except: pass
            time.sleep(Config.API_THROTTLE_SLEEP) # 保護 API (1.2s)

        # 💡 每輪掃描完畢後的休眠機制 (10s)
        print(f"\n✅ 當前輪次結束，休息 {Config.ROUND_INTERVAL_SLEEP} 秒後繼續下一次偵察...")
        time.sleep(Config.ROUND_INTERVAL_SLEEP)

if __name__ == "__main__":
    main()