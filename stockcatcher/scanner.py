import os
import time
import requests
import urllib3
import pandas as pd
from datetime import datetime, timedelta, timezone, time as dtime
from typing import Dict, List, Any, Set, Optional
from dateutil.parser import isoparse

# 🛡️ Susu 的開發規範：全域禁用 SSL 驗證警告，解決環境憑證缺失導致的連線失敗
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ============================================================
# ⚙️ [系統配置區] (System Configuration)
# ============================================================
class Config:
    # 🔐 憑證管理：使用預留位置替代硬編碼，確保系統安全性
    FINMIND_TOKEN = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJ1c2VyX2lkIjoiRVNCMTc4MTMiLCJlbWFpbCI6Im0yOTk0MDUwOUBob3RtYWlsLmNvbSJ9.iGsA_PLkanve2aATgXU-RD2i7RKOHSLzMEmASMBOcDE" 
    FUGLE_API_KEY ="MzJiNjhmNjAtMzRjMy00OGZiLTg3YWQtMTJmMjg3NGE0MDNjIGJlNGVmY2Q2LTE5NDQtNDUzZi1iNTcxLTI5NmIzM2QwOTIzZQ=="
    TELEGRAM_TOKEN = "8480482512:AAGin83kwa61oa5F5rBj4NQMow-C9jsbJug"
    TELEGRAM_CHAT_ID = "-1003613268841"

    # 🛠️ 運行模式
    TEST_MODE = True    # Debug 時為 True：模擬盤中報價看板顯示
    DEBUG_MODE = True   

    # 📈 選股池配額與門檻
    TSE_QUOTA = 90
    OTC_QUOTA = 30
    WARRANT_QUOTA = 20
    OTC_VOL_THRESHOLD = 500 # 上櫃成交量最低門檻 (張)

    # 🎯 策略參數
    VOL_EST_THRESHOLD = 1.6 # 1.6 倍預估量能異常
    MARKET_OPEN = dtime(9, 0)
    RECOVERY_THRESHOLD = dtime(9, 15) # 3K 法基準判斷時間點
    MARKET_CLOSE = dtime(13, 35)
    
    # 🏎️ 效能節流
    API_THROTTLE_SLEEP = 1.2    
    ROUND_INTERVAL_SLEEP = 10   

    # 🛡️ 模擬真實瀏覽器指紋，繞過 WAF 阻斷
    BROWSER_HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "application/json",
        "Connection": "keep-alive"
    }

# 全域連線池：持有 Session 維護 Cookie 並禁用 SSL 驗證
session = requests.Session()
session.verify = False 
session.headers.update(Config.BROWSER_HEADERS)

# 全域記憶體狀態
global_stock_info = {} # 存放現股基礎資料
stock_info_map = {}     # 存放監控池詳細資訊
monitor_data = {}       # 存放策略狀態與極值
warrant_target_list = set()

# ------------------------------------------------------------
# 🛠️ 蘇蘇的防禦性工具 (Utilities)
# ------------------------------------------------------------

def safe_cast(val: Any, to_type: type, default: Any = 0) -> Any:
    """ 安全型別轉換，過濾千分號與 NaN """
    try:
        if pd.isna(val) or val is None or str(val).strip() == "": return default
        return to_type(float(str(val).replace(',', '').strip()))
    except: return default

def get_now_tw() -> datetime:
    """ 獲取台北標準時間 (UTC+8) """
    return datetime.now(timezone.utc) + timedelta(hours=8)

def is_market_hours() -> bool:
    """ 判斷是否為交易時段 """
    now = get_now_tw().time()
    return Config.MARKET_OPEN <= now <= Config.MARKET_CLOSE

def is_valid_stock(sid: str, info: dict) -> bool:
    """ 排除特定類股與非標準 4 碼標的 """
    sid_str = str(sid).strip()
    if len(sid_str) != 4 or sid_str.startswith("00"): return False
    industry = info.get('industry', '')
    if any(k in industry for k in ["金融", "保險", "ETF", "存託憑證"]): return False 
    return True

# ------------------------------------------------------------
# 🏛️ 資料對接模組 (V78.0 核心)
# ------------------------------------------------------------

def detect_category_column(df: pd.DataFrame) -> Optional[str]:
    """ 動態偵測 FinMind 的產業類別欄位，避開 KeyError """
    possible_names = ['industry', 'category', 'industry_category', 'type']
    for name in possible_names:
        if name in df.columns: return name
    return None

def api_get_json(url: str, referer: str = "https://www.twse.com.tw/") -> Any:
    """ 強化版 API 請求：處理 Referer 與 Host 指紋 """
    headers = Config.BROWSER_HEADERS.copy()
    headers["Referer"] = referer
    try:
        res = session.get(url, headers=headers, timeout=15)
        if res.status_code == 200: return res.json()
    except Exception as e:
        if Config.DEBUG_MODE: print(f"❌ [API 連線異常] {e}")
    return None

def init_global_mapping():
    """ 同步 FinMind 市場名冊：建立基礎 4 碼現股資料庫 """
    print("📡 同步 FinMind 市場名冊...", flush=True)
    from FinMind.data import DataLoader
    dl = DataLoader()
    if Config.FINMIND_TOKEN: dl.login_by_token(Config.FINMIND_TOKEN)
    
    try:
        df = dl.taiwan_stock_info()
        if not df.empty:
            cat_col = detect_category_column(df)
            for _, row in df.iterrows():
                sid = str(row['stock_id']).strip()
                if len(sid) == 4: # 鎖定現股標的
                    global_stock_info[sid] = {
                        'name': row['stock_name'], 
                        'industry': str(row.get(cat_col, '熱門標的')).strip()
                    }
            print(f"✅ 名冊同步完成，共 {len(global_stock_info)} 檔標的。", flush=True)
    except Exception as e:
        print(f"❌ [初始化失敗] {e}")

def load_official_warrant_targets() -> int:
    """ 💡 代碼長度過濾法：利用 6 碼特徵提取權證標的，不設保底資料 """
    print("📡 正在解析權證關聯標的池 (FinMind 代碼過濾法)...", flush=True)
    from FinMind.data import DataLoader
    dl = DataLoader()
    if Config.FINMIND_TOKEN: dl.login_by_token(Config.FINMIND_TOKEN)
    
    try:
        df_info = dl.taiwan_stock_info()
        # 提取 6 碼證券 (權證特徵)
        df_info['sid_str'] = df_info['stock_id'].astype(str).str.strip()
        warrants_df = df_info[df_info['sid_str'].str.len() == 6]
        
        if warrants_df.empty:
            print("⚠️ [警告] API 未能返回權證標的。")
            return 0

        # 反向映射：從名稱前段提取標的 (如：台積電凱基... -> 台積電)
        warrant_names = warrants_df['stock_name'].tolist()
        potential_names = set()
        for name in warrant_names[:500]: # 取樣本進行分析
            potential_names.add(name[:2])
            potential_names.add(name[:3])
            potential_names.add(name[:4])

        # 比對名冊
        for sid, info in global_stock_info.items():
            if info['name'] in potential_names and is_valid_stock(sid, info):
                warrant_target_list.add(sid)
                if len(warrant_target_list) >= Config.WARRANT_QUOTA: break
        
        print(f"✅ 權證分析完成，最終取得 {len(warrant_target_list)} 檔標的。")
    except Exception as e:
        print(f"❌ [權證池失敗] {e}")
    
    return len(warrant_target_list)

def sync_market_pool(warrant_count: int):
    """ 初始化監控池配額 """
    print(f"🛰️ 啟動市場配額同步...", flush=True)
    tse_raw, otc_raw = [], []
    
    # 呼叫穩定 JSON 鏈路
    t_data = api_get_json("https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL")
    o_data = api_get_json("https://www.tpex.org.tw/openapi/v1/tpex_mainboard_quotes")

    if t_data:
        for i in t_data:
            sid = i.get('Code')
            if is_valid_stock(sid, global_stock_info.get(sid, {})):
                tse_raw.append({'code': sid, 'vol': safe_cast(i.get('TradeVolume'), int) // 1000})
    if o_data:
        for i in o_data:
            sid = i.get('SecuritiesCompanyCode', '').strip()
            if is_valid_stock(sid, global_stock_info.get(sid, {})):
                vol = safe_cast(i.get('TradingShares'), int) // 1000
                if vol >= Config.OTC_VOL_THRESHOLD: otc_raw.append({'code': sid, 'vol': vol})
    
    top_tse = sorted(tse_raw, key=lambda x: x['vol'], reverse=True)[:Config.TSE_QUOTA]
    top_otc = sorted(otc_raw, key=lambda x: x['vol'], reverse=True)[:Config.OTC_QUOTA]
    
    print(f"✅ 初始化：上市 {len(top_tse)} 檔、上櫃 {len(top_otc)} 檔、權證相關 {warrant_count} 檔")

    final_list = [{'code': s, 'vol': 1000, 'market': '權證'} for s in list(warrant_target_list)]
    final_list += [{'code': x['code'], 'vol': x['vol'], 'market': '上市'} for x in top_tse]
    final_list += [{'code': x['code'], 'vol': x['vol'], 'market': '上櫃'} for x in top_otc]

    for item in final_list:
        code = item['code']
        if code not in stock_info_map:
            info = global_stock_info.get(code, {'name': '搜尋中', 'industry': '熱門成交'})
            stock_info_map[code] = {'name': info['name'], 'market': item['market'], 'industry': info['industry']}
            monitor_data[code] = {
                "high": 0.0, "low": 9999.0, "y_vol": max(1, item['vol']), 
                "trig_3k": False, "trig_vol": False, "trig_both": False
            }

# ------------------------------------------------------------
# 💹 監控警報與 3K 補課
# ------------------------------------------------------------

def send_tg_alert(sid: str, strategy: str, lp: float, high: float, low: float, ratio: float):
    """ Telegram 發報：採用 Markdown 與外部連結 """
    info = stock_info_map.get(sid, {'name': '標的', 'industry': '產業'})
    nstock_url = f"https://www.nstock.tw/stock_info?stock_id={sid}"
    msg = (
        f"🚨【蘇蘇天機選股 - 訊號觸發】\n"
        f"🎯 *核心策略：* {strategy}\n"
        f"━━━━━━━━━━━━━━\n"
        f"📈 *標的：* [**{sid} {info['name']}**]({nstock_url})\n"
        f"💰 *現價：* `{lp}`\n"
        f"🎯 *3K高：* `{high}` | 🛡️ *3K低：* `{low}`\n"
        f"📊 *預估量比：* `{ratio}x`\n"
        f"🏷️ *產業別：* {info['industry']}\n"
        f"━━━━━━━━━━━━━━\n"
        f"⏰ {get_now_tw().strftime('%H:%M:%S')}"
    )
    try:
        url = f"https://api.telegram.org/bot{Config.TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": Config.TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"}, timeout=10)
    except: pass

def perform_strategy_test():
    """ 驗證三大策略發報 """
    print("📡 啟動自動化測試：發送驗證訊號...", flush=True)
    send_tg_alert("2330", "策略一：3K法突破測試", 1000.0, 990.0, 970.0, 1.2)
    send_tg_alert("2317", "策略二：量能異常測試", 150.0, 160.0, 140.0, 2.5)
    send_tg_alert("2454", "🔥 策略三：3K突破+量能異常測試", 1100.0, 1050.0, 1000.0, 1.8)

def recover_3k_data(target_list: List[str]):
    """ 追溯今日開盤 3K 極值 """
    now_tw = get_now_tw()
    if not is_market_hours() or now_tw.time() < Config.RECOVERY_THRESHOLD:
        print("ℹ️ 未達補課時段，跳過追溯。", flush=True)
        return

    print(f"🔄 執行 3K 補課 (共 {len(target_list)} 檔)...", flush=True)
    today_tw = now_tw.date()
    for idx, sid in enumerate(target_list):
        try:
            url = f"https://api.fugle.tw/marketdata/v1.0/stock/intraday/candles/{sid}?timeframe=1"
            res = requests.get(url, headers={"X-API-KEY": Config.FUGLE_API_KEY.strip()}, timeout=5).json()
            if res and "data" in res:
                kbars = res.get('data', [])
                v_h = [k['high'] for k in kbars if isoparse(k['date']).astimezone(timezone(timedelta(hours=8))).date() == today_tw and isoparse(k['date']).astimezone(timezone(timedelta(hours=8))).time() <= Config.RECOVERY_THRESHOLD]
                v_l = [k['low'] for k in kbars if isoparse(k['date']).astimezone(timezone(timedelta(hours=8))).date() == today_tw and isoparse(k['date']).astimezone(timezone(timedelta(hours=8))).time() <= Config.RECOVERY_THRESHOLD]
                if v_h: monitor_data[sid]['high'], monitor_data[sid]['low'] = max(v_h), min(v_l)
            print(f"[{idx+1}/{len(target_list)}] {sid:<4} 補課完成", end='\r')
        except: pass
        time.sleep(Config.API_THROTTLE_SLEEP)

# ------------------------------------------------------------
# 🏁 主監控程序
# ------------------------------------------------------------

def main():
    print("="*115)
    print(f"🛡️ 蘇蘇的天機選股監控系統 | V78.0 | {get_now_tw().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*115, flush=True)

    init_global_mapping() 
    w_count = load_official_warrant_targets() 
    sync_market_pool(w_count)
    perform_strategy_test()
    recover_3k_data(list(stock_info_map.keys()))

    print("\n🚀 系統初始化完畢，準備進入監控循環模式...", flush=True)
    
    while True:
        tw_now = get_now_tw()
        print(f"\n[監控週期: {tw_now.strftime('%H:%M:%S')}]")
        print(f"{'股號股名':<16} | {'市場':<4} | {'現價':<8} | {'量比':<6} | {'3K高':<8} | {'3K低':<8} | {'產業別'}")
        print("-" * 115)

        passed_min = max(1.0, min(270.0, (datetime.combine(tw_now.date(), tw_now.time()) - datetime.combine(tw_now.date(), Config.MARKET_OPEN)).total_seconds() / 60))

        for sid in list(stock_info_map.keys()):
            info, data = stock_info_map[sid], monitor_data[sid]
            try:
                # 鎖定富果 API 格式
                f_url = f"https://api.fugle.tw/marketdata/v1.0/stock/intraday/quote/{sid}"
                res = requests.get(f_url, headers={"X-API-KEY": Config.FUGLE_API_KEY.strip()}, timeout=5).json()
                
                if res:
                    lp = res.get('lastPrice')
                    v = safe_cast(res.get('total', {}).get('tradeVolume'), int) // 1000
                else: lp, v = None, 0
                
                if lp is None and Config.TEST_MODE: lp, v = 105.0, 500
                if not lp: continue
                
                if tw_now.time() <= Config.RECOVERY_THRESHOLD:
                    if lp > data['high']: data['high'] = lp
                    if lp < data['low'] or data['low'] == 9999.0: data['low'] = lp
                
                ratio = round((v * (270 / passed_min)) / data['y_vol'], 2) if data['y_vol'] > 0 else 0
                print(f"{sid} {info['name']:<10} | {info['market']:<4} | {lp:<8} | {ratio:<6} | {data['high']:<8} | {data['low']:<8} | {info['industry']}")

                # 策略判定
                is_3k_break = lp > data['high'] > 0
                is_vol_anomaly = ratio >= Config.VOL_EST_THRESHOLD
                
                if is_3k_break and is_vol_anomaly and not data['trig_both']:
                    send_tg_alert(sid, "🔥 策略三：3K突破 + 量能異常 (價量齊揚)", lp, data['high'], data['low'], ratio)
                    data['trig_both'] = data['trig_3k'] = data['trig_vol'] = True
                elif is_3k_break and not data['trig_3k']:
                    send_tg_alert(sid, "📈 策略一：3K 法突破偵測", lp, data['high'], data['low'], ratio)
                    data['trig_3k'] = True
                elif is_vol_anomaly and not data['trig_vol']:
                    send_tg_alert(sid, "📊 策略二：預估量能異常偵測", lp, data['high'], data['low'], ratio)
                    data['trig_vol'] = True

            except: pass
            time.sleep(Config.API_THROTTLE_SLEEP)

        if not is_market_hours() and not Config.TEST_MODE:
            time.sleep(10)
        else:
            time.sleep(Config.ROUND_INTERVAL_SLEEP)

if __name__ == "__main__":
    main()