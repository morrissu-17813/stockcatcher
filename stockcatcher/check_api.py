import os
import time
import re
import sys
import math
from datetime import datetime, timedelta, timezone, time as dtime
from typing import List
from dateutil.parser import isoparse
from dotenv import load_dotenv

# ⚡ 核心變更：引入 curl_cffi 偽裝 Chrome 瀏覽器，徹底繞過 SSL 憑證驗證失敗
from curl_cffi import requests as curl_requests
import requests as standard_requests

# 🛡️ 禁用 urllib3 不安全請求警告與載入環境變數
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
load_dotenv()

# ============================================================
# ⚙️ [系統配置區] - 實戰參數落鎖
# ============================================================
class Config:
    FINMIND_TOKEN = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJ1c2VyX2lkIjoiRVNCMTc4MTMiLCJlbWFpbCI6Im0yOTk0MDUwOUBob3RtYWlsLmNvbSJ9.iGsA_PLkanve2aATgXU-RD2i7RKOHSLzMEmASMBOcDE"
    FUGLE_API_KEY = "MzJiNjhmNjAtMzRjMy00OGZiLTg3YWQtMTJmMjg3NGE0MDNjIGJlNGVmY2Q2LTE5NDQtNDUzZi1iNTcxLTI5NmIzM2QwOTIzZQ=="
    TELEGRAM_TOKEN = "8480482512:AAGin83kwa61oa5F5rBj4NQMow-C9jsbJug"
    TELEGRAM_CHAT_ID = "1087480334"

    # 📊 配額管理
    MAX_POOL_SIZE      = 170
    WARRANT_QUOTA      = 20    
    LISTED_QUOTA       = 100    
    OTC_QUOTA          = 50    
    SCAN_INTERVAL      = 900   

    # 🎯 策略爆發門檻
    ENTRY_MIN_PCT      = 3.5   
    ENTRY_MAX_PCT      = 9.0   
    GRADUATION_PCT     = 9.7   
    VOL_EST_THRESHOLD  = 2.0   # ✅ 量能門檻依指示下修至 2.0

    # ⏰ 時間控制
    MARKET_OPEN        = dtime(9, 0)
    MARKET_CLOSE       = dtime(13, 30)
    AUTO_SHUTDOWN_TIME = dtime(13, 35)  
    RECOVERY_THRESHOLD = dtime(9, 15)  
    API_THROTTLE_SLEEP = 1.1   
    TEST_MODE          = True # 實戰時請保持 False

# 🗄️ 全域記憶體容器與快照矩陣
stock_info_map = {}   
monitor_data = {}     
finmind_industry_map = {} 
global_volume_lookup = {}  
last_scan_time = 0
_exchange_map = {}        
_last_fugle_scan = 0.0    
_mis_session = None       

# ============================================================
# 🛡️ 🔏 [真．全域落鎖區] 核心工具與通訊函數強制置頂
# ============================================================

def get_now_tw():
    """ 取得當前台北時間 """
    return datetime.now(timezone.utc) + timedelta(hours=8)

def is_market_hours():
    now_time = get_now_tw().time()
    return Config.MARKET_OPEN <= now_time <= Config.MARKET_CLOSE

def get_stock_exchange(sid):
    market = stock_info_map.get(sid, {}).get('market', '')
    if market == '上市': return 'tse'
    if market == '上櫃': return 'otc'
    return _exchange_map.get(sid, 'tse')

def wide_ljust(text, width, fillchar=' '):
    text = str(text)
    count = sum(1 for ch in text if ord(ch) > 127)
    return text.ljust(width - count, fillchar)

def get_consumption_badge(rate: float) -> str:
    pct = int(rate * 100)
    if pct >= 80: return f"🟢 {pct}%"
    if pct >= 40: return f"🟡 {pct}%"
    return f"🔴 {pct}%"

def safe_cast(value, target_type, default=0):
    if value is None: return default
    try:
        str_val = str(value).replace(',', '').strip()
        if not str_val: return default
        f = float(str_val)
        if math.isnan(f): return default
        return target_type(f)
    except (ValueError, TypeError):
        return default

def send_tg_alert(sid, strategy_name, lp, high=0.0, low=0.0, ratio=0.0, up_pct=0.0):
    """ Telegram 發報模組 """
    # 🌟 [漲停物理阻斷] 漲幅大於等於 9.75% 視為漲停，絕對阻斷發報！
    if up_pct >= 9.75:
        return
        
    info = stock_info_map.get(sid, {})
    data = monitor_data.get(sid, {})
    
    # 🌟 [CD 冷卻鎖] 30分鐘內 (1800秒) 同檔股票絕對不重複發送，維持 Telegram 乾淨！
    if time.time() - data.get('last_alert_time', 0) < 1800:
        return
        
    badge = "🎫 [權證主力標的] " if info.get('is_protected') else f"[{info.get('market', '未知')}] "
    scenario = "🚨 [訊號觸發]" 
    consumption_str = get_consumption_badge(data.get('last_consumption', 0.45))
    is_acc = data.get('is_accelerating', False)
    stop_loss_price = low if low > 0 else lp
    
    msg = (
        f"{scenario}\n"
        f"🎯 *核心策略：* {badge}{strategy_name}\n"
        f"━━━━━━━━━━━━━━\n"
        f"📈 *標的：* [{sid} {info.get('name', '')}](https://www.nstock.tw/stock_info?stock_id={sid})\n"
        f"💰 *現價：* `{lp}` (漲幅: {up_pct}%)\n"
        f"📊 *預估量比：* `{ratio}x`\n"        
        f"📐 *3K高位：* `{high}`\n"
        f"📐 *3K低位：* `{low}`\n"
        f"🛡️ *策略停損：* `{stop_loss_price}`\n"
        f"💥 *壓力消化：* {consumption_str}\n"
        f"🚀 *能量斜率：* {'陡增' if is_acc else '平穩'}\n"
        f"🏷️ *產業類別：* `{info.get('industry', '未知產業')}`\n"
        f"━━━━━━━━━━━━━━\n"
        f"⏰ {get_now_tw().strftime('%H:%M:%S')}"
    )
    url = f"https://api.telegram.org/bot{Config.TELEGRAM_TOKEN}/sendMessage"
    try:
        standard_requests.post(url, json={"chat_id": Config.TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"}, timeout=5)
        # ✅ 發送成功後更新冷卻時間鎖
        data['last_alert_time'] = time.time()
    except Exception as e:
        print(f"[錯誤] Telegram 發送通知失敗: {e}")

# ------------------------------------------------------------
# 🛡️ 金融股、保險股、ETF 全物理絕緣過濾器
# ------------------------------------------------------------
def should_exclude(sid, name, industry):
    sid = str(sid).strip()
    name = str(name)
    industry = str(industry)
    if sid.startswith('00') or sid.startswith('01') or sid.startswith('03') or \
       any(k in name for k in ["ETF", "受益憑證", "基金", "指數", "債券", "存託憑證"]) or \
       any(k in industry for k in ["ETF", "受益憑證", "指數", "債券", "存託憑證"]):
        return True
    if sid.startswith('28') or sid.startswith('58') or sid.startswith('60') or \
       any(k in name for k in ["金控", "銀行", "保險", "證券", "人壽", "信託", "期貨"]) or \
       any(k in industry for k in ["金融", "保險", "證券", "金控"]):
        return True
    return False

def fetch_disposition_stocks():
    disposition_set = set()
    try:
        url_notice = "https://openapi.twse.com.tw/v1/announcement/notice"
        res_notice = curl_requests.get(url_notice, impersonate="chrome120", timeout=5).json()
        for item in res_notice:
            sid = item.get('證券代號', '').strip()
            if sid: disposition_set.add(sid)
    except Exception: pass
    return disposition_set

# ------------------------------------------------------------
# ⚡ 快速層 - TWSE/TPEx 官方 Cookie 連動會話模組
# ------------------------------------------------------------

def fetch_mis_batch_all():
    global _mis_session
    if _mis_session is None:
        _mis_session = curl_requests.Session()
        try: _mis_session.get("https://mis.twse.com.tw/stock/index.jsp", impersonate="chrome120", timeout=6)
        except: pass
        
    results = {}
    all_sids = list(stock_info_map.keys())
    if not all_sids: return results
    
    BATCH_SIZE = 25  
    for i in range(0, len(all_sids), BATCH_SIZE):
        batch = all_sids[i:i + BATCH_SIZE]
        ex_ch = '|'.join(f"{get_stock_exchange(s)}_{s}.tw" for s in batch)
        url = f"https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch={ex_ch}&_={int(time.time()*1000)}"
        try:
            res = _mis_session.get(url, impersonate="chrome120", timeout=6).json()
            for item in res.get('msgArray', []):
                sid = item.get('c', '').strip()
                if not sid: continue
                z = item.get('z', '-')
                y = safe_cast(item.get('y', '0'), float)
                lp = y if (z in ('-', '0') or safe_cast(z, float) <= 0) else safe_cast(z, float)
                if lp <= 0: continue
                v = safe_cast(item.get('v', '0').replace(',', ''), int)   
                f_str = item.get('f', '')
                ask3 = sum(safe_cast(x, int) for x in f_str.split('_')[:3]) if f_str else 0
                up_pct = round((lp - y) / y * 100, 2) if y > 0 else 0.0
                results[sid] = {'lp': lp, 'v': v, 'ask3': ask3, 'up_pct': up_pct}
        except Exception: pass
    return results

# ------------------------------------------------------------
# 🏢 官方免 Token 雙重產業 Profile 大數據庫
# ------------------------------------------------------------

def fetch_finmind_industry_mapping():
    mapping = {
        "2330": {"name": "台積電", "industry": "半導體業"}, "2317": {"name": "鴻海", "industry": "其他電子業"},
        "2454": {"name": "聯發科", "industry": "半導體業"}, "2382": {"name": "廣達", "industry": "電腦週邊業"},
        "3231": {"name": "緯創", "industry": "電腦週邊業"}, "3037": {"name": "欣興", "industry": "電子零組件業"},
        "2618": {"name": "長榮航", "industry": "航運業"}, "2603": {"name": "長榮", "industry": "航運業"},
        "8069": {"name": "元太", "industry": "光電業"}, "6531": {"name": "愛普*", "industry": "半導體業"},
        "3481": {"name": "群創", "industry": "光電業"}, "8299": {"name": "群聯", "industry": "半導體業"}
    }
    try:
        twse_profile = curl_requests.get("https://openapi.twse.com.tw/v1/opendata/t187ap03_L", impersonate="chrome120", timeout=10).json()
        if isinstance(twse_profile, list):
            for row in twse_profile:
                sid = row.get('公司代號', '').strip()
                if len(sid) == 4:
                    mapping[sid] = {"name": row.get('公司簡稱', '').strip(), "industry": row.get('產業類別', '上市其他').strip()}
    except Exception: pass
    try:
        tpex_profile = curl_requests.get("https://www.tpex.org.tw/openapi/v1/tpex_mainboard_profile", impersonate="chrome120", timeout=10).json()
        if isinstance(tpex_profile, list):
            for row in tpex_profile:
                sid = str(row.get('SecuritiesCompanyCode', '')).strip()
                if len(sid) == 4:
                    mapping[sid] = {"name": row.get('CompanyName', '').strip(), "industry": row.get('IndustryCategory', '上櫃其他').strip()}
    except Exception: pass
    return mapping

# ------------------------------------------------------------
# 🔄 汰換引擎（100% 依據全市場真實成交量大排序）
# ------------------------------------------------------------

def fetch_market_candidates(market_type="上市"):
    candidates = []
    disposition_set = fetch_disposition_stocks()
    try:
        if market_type == "上市":
            url = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
            res = curl_requests.get(url, impersonate="chrome120", timeout=10).json()
            rows = res if isinstance(res, list) else []
            for i in rows:
                sid = i.get('Code')
                if not sid or len(sid) != 4 or sid in disposition_set or sid in stock_info_map: continue
                fm = finmind_industry_map.get(sid, {"name": i.get('Name', f"上市_{sid}").strip(), "industry": "電子零組件業"})
                if should_exclude(sid, fm['name'], fm['industry']): continue
                vol = safe_cast(i.get('TradeVolume'), int) // 1000  
                candidates.append({'sid': sid, 'up_pct': 0.0, 'vol': vol, 'market': '上市', 'name': fm['name'], 'ind': fm['industry']})
        else:
            url = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_quotes"
            res = curl_requests.get(url, impersonate="chrome120", timeout=10).json()
            rows = res if isinstance(res, list) else []
            for i in rows:
                sid = i.get('SecuritiesCompanyCode', '').strip()
                if not sid or len(sid) != 4 or sid in disposition_set or sid in stock_info_map: continue
                raw_name = i.get('CompanyName', i.get('SecuritiesCompanyName', f"上櫃_{sid}")).strip()
                fm = finmind_industry_map.get(sid, {"name": raw_name, "industry": "半導體業"})
                if should_exclude(sid, fm['name'], fm['industry']): continue
                vol = safe_cast(i.get('TradingShares'), int) // 1000  
                candidates.append({'sid': sid, 'up_pct': 0.0, 'vol': vol, 'market': '上櫃', 'name': fm['name'], 'ind': fm['industry']})
        candidates = sorted(candidates, key=lambda x: x['vol'], reverse=True)
    except Exception: pass
    return candidates

def refresh_pool_v90():
    global last_scan_time
    now = time.time()
    if now - last_scan_time < Config.SCAN_INTERVAL and len(stock_info_map) >= 120: return
    last_scan_time = now
    
    market_configs = [
        {"type": "上市", "quota": Config.LISTED_QUOTA, "fetch_func": lambda: fetch_market_candidates("上市")},
        {"type": "上櫃", "quota": Config.OTC_QUOTA, "fetch_func": lambda: fetch_market_candidates("上櫃")}
    ]

    for config in market_configs:
        m_type, m_quota = config["type"], config["quota"]
        candidates = config["fetch_func"]()
        
        current_dynamic_sids = [s for s in stock_info_map if stock_info_map[s]['market'] == m_type and not stock_info_map[s].get('is_protected')]
        to_remove_count = max(0, len(current_dynamic_sids) + len(candidates) - m_quota)
        to_remove_list = list(set(current_dynamic_sids))[:to_remove_count]
        
        for rsid in to_remove_list:
            stock_info_map.pop(rsid, None)
            monitor_data.pop(rsid, None)

        remaining = len([s for s in stock_info_map if stock_info_map[s]['market'] == m_type and not stock_info_map[s].get('is_protected')])
        vacancy = m_quota - remaining

        for cand in sorted(candidates, key=lambda x: x['vol'], reverse=True)[:vacancy]:
            csid = cand['sid']
            stock_info_map[csid] = {'name': cand['name'], 'market': m_type, 'is_protected': False, 'industry': cand['ind']}
            monitor_data[csid] = {
                "high": 0.0, "low": 9999.0, "y_vol": cand['vol'], 
                "trig_both": False, "trig_3k": False, "trig_vol": False, "trig_策略四": False,
                "state": 0, "point_a": 0.0, "point_b": 9999.0,  
                "last_alert_time": 0, "last_up_pct": 0.0, "last_ratio": 1.0, "last_consumption": 0.0, "is_accelerating": False, "history_prices": []
            }

# ------------------------------------------------------------
# 🕵️‍♂️ ✅ [雙軌權證大核流] 優先 FinMind API，元大權證網備援
# ------------------------------------------------------------

def load_official_warrant_targets() -> List[str]:
    """ 💡 主方案：FinMind 代碼長度過濾法 (加入 Token 異常容錯) """
    print("📡 正在解析權證關聯標的池 (FinMind 官方 API)...", flush=True)
    warrant_target_list = set()
    try:
        from FinMind.data import DataLoader
        dl = DataLoader()
        try:
            if Config.FINMIND_TOKEN: 
                dl.login_by_token(Config.FINMIND_TOKEN)
        except Exception as auth_e:
            print(f"⚠️ FinMind Token 登入異常，自動降級為無 Token 訪客模式: {auth_e}")
        
        df_info = dl.taiwan_stock_info()
        df_info['sid_str'] = df_info['stock_id'].astype(str).str.strip()
        warrants_df = df_info[df_info['sid_str'].str.len() == 6]
        
        if warrants_df.empty:
            print("⚠️ [警告] API 未能返回權證標的，將自動切換備援。")
            return []

        warrant_names = warrants_df['stock_name'].tolist()
        potential_names = set()
        for name in warrant_names[:500]: 
            potential_names.add(name[:2])
            potential_names.add(name[:3])
            potential_names.add(name[:4])

        for sid, info in finmind_industry_map.items():
            if any(n in info['name'] for n in potential_names):
                warrant_target_list.add(sid)
                if len(warrant_target_list) >= Config.WARRANT_QUOTA: break
        
        print(f"✅ 權證分析完成，取得 {len(warrant_target_list)} 檔標的。")
    except Exception as e:
        print(f"❌ [FinMind 權證池失敗] {e}，將切換備援。")
    
    return list(warrant_target_list)

def scrape_yuanta_hot_targets_fallback() -> List[str]:
    """ 💡 備胎方案：元大權證網 (WarrantWin) 熱門標的穿透提取 """
    results = []
    # 鎖定元大權證網的熱門排行榜頁面
    url = "https://www.warrantwin.com.tw/eyuanta/Warrant/HotTarget.aspx"
    try:
        # 強制使用 curl_cffi 偽裝 Chrome120，繞過所有的反爬蟲與 SSL 檢測
        res = curl_requests.get(url, impersonate="chrome120", timeout=15)
        if res.status_code == 200:
            text = res.text
            # 掃描網頁原始碼中潛在的 4 碼股票代號
            codes = re.findall(r'\b([0-9]{4})\b', text)
            
            # 使用 global_volume_lookup 當作驗證器，只抓取真正的股票代號
            for sid in codes:
                if sid in global_volume_lookup and sid not in results and sid not in ['1999', '2024', '2025', '2026', '0800']:
                    results.append(sid)
            print(f"console.log: [備援探針] 元大權證網提取成功！取得 {len(results)} 檔標的")
    except Exception as e:
        print(f"console.log: [備援探針] 元大權證網 鏈路異常: {e}")
    return results

def pre_market_initialization():
    global global_volume_lookup
    twse_sids = set()
    disposition_set = fetch_disposition_stocks()

    # 🌐 建立全台當日真．成交量能數據庫
    try:
        twse_data = curl_requests.get("https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL", impersonate="chrome120", timeout=10).json()
        if isinstance(twse_data, list):
            for row in twse_data:
                code = row.get('Code', '').strip()
                if len(code) == 4:
                    global_volume_lookup[code] = safe_cast(row.get('TradeVolume'), int) // 1000
                    twse_sids.add(code)
    except: pass
    try:
        tpex_data = curl_requests.get("https://www.tpex.org.tw/openapi/v1/tpex_mainboard_quotes", impersonate="chrome120", timeout=10).json()
        if isinstance(tpex_data, list):
            for row in tpex_data:
                code = str(row.get('SecuritiesCompanyCode', '')).strip()
                if len(code) == 4: global_volume_lookup[code] = safe_cast(row.get('TradingShares'), int) // 1000
    except: pass

    # ✅ 1. 優先使用 FinMind 主力方案
    clean_sids = load_official_warrant_targets()
    
    # ✅ 2. 若 FinMind 失敗或陣亡，啟動 元大權證網 備胎補滿
    if len(clean_sids) < Config.WARRANT_QUOTA:
        fallback_sids = scrape_yuanta_hot_targets_fallback()
        for sid in fallback_sids:
            if sid not in clean_sids:
                clean_sids.append(sid)
            if len(clean_sids) >= Config.WARRANT_QUOTA: break

    injected = 0
    for sid in clean_sids:
        if sid in disposition_set: continue
        
        ind = finmind_industry_map.get(sid, {}).get('industry', '權證熱門標的')
        name = finmind_industry_map.get(sid, {}).get('name', f"現股_{sid}")
        if should_exclude(sid, name, ind): continue
        
        if sid not in stock_info_map:
            y_vol_base = global_volume_lookup.get(sid, 1500)
            if y_vol_base < 100: y_vol_base = 1500 
            _exchange_map[sid] = 'tse' if sid in twse_sids else 'otc'
            stock_info_map[sid] = {'name': name, 'market': '權證', 'is_protected': True, 'industry': ind}
            monitor_data[sid] = {
                "high": 0.0, "low": 9999.0, "y_vol": y_vol_base, 
                "trig_both": False, "trig_3k": False, "trig_vol": False, "trig_策略四": False,
                "state": 0, "point_a": 0.0, "point_b": 9999.0,  
                "last_alert_time": 0, "last_up_pct": 0.0, "last_ratio": 1.0, "last_consumption": 0.85, "is_accelerating": True, "history_prices": []
            }
            injected += 1
            if injected >= Config.WARRANT_QUOTA: break
            
    print(f"真．動態權證現股化分析完成，最終注入 {injected} 檔實時熱門標的。")

def recover_3k_data(target_list: List[str]):
    now_tw = get_now_tw()
    if not is_market_hours() or now_tw.time() < Config.RECOVERY_THRESHOLD: return
    print(f"🔄 執行 3K 補課 (共 {len(target_list)} 檔)...", flush=True)
    today_tw = now_tw.date()
    for idx, sid in enumerate(target_list):
        try:
            url = f"https://api.fugle.tw/marketdata/v1.0/stock/intraday/candles/{sid}?timeframe=1"
            res = standard_requests.get(url, headers={"X-API-KEY": Config.FUGLE_API_KEY.strip()}, timeout=5).json()
            if res and "data" in res:
                kbars = res.get('data', [])
                v_h = [k['high'] for k in kbars if isoparse(k['date']).astimezone(timezone(timedelta(hours=8))).date() == today_tw and isoparse(k['date']).astimezone(timezone(timedelta(hours=8))).time() <= Config.RECOVERY_THRESHOLD]
                v_l = [k['low'] for k in kbars if isoparse(k['date']).astimezone(timezone(timedelta(hours=8))).date() == today_tw and isoparse(k['date']).astimezone(timezone(timedelta(hours=8))).time() <= Config.RECOVERY_THRESHOLD]
                if v_h: monitor_data[sid]['high'], monitor_data[sid]['low'] = max(v_h), min(v_l)
        except: pass
        time.sleep(Config.API_THROTTLE_SLEEP)

# ------------------------------------------------------------
# 🎬 主程式核心驅動流
# ------------------------------------------------------------

def main():
    global _last_fugle_scan, finmind_industry_map
    print(f"🛡️ 蘇蘇的天機選股 V112.0 啟動完成。")
    print(f"{get_now_tw().strftime('%H:%M:%S')} 執行盤前籌碼映射與官方 Profile 基本面同步...")
    
    finmind_industry_map = fetch_finmind_industry_mapping()
    pre_market_initialization()
    print("🛰️ 啟動市場配額同步...")
    refresh_pool_v90()
    
    w_count = len([s for s in stock_info_map if stock_info_map[s]['market'] == '權證'])
    l_count = len([s for s in stock_info_map if stock_info_map[s]['market'] == '上市'])
    o_count = len([s for s in stock_info_map if stock_info_map[s]['market'] == '上櫃'])
    print(f"✅ 初始化：上市 {l_count} 檔、上櫃 {o_count} 檔、權證相關現股 {w_count} 檔")
    
    recover_3k_data(list(stock_info_map.keys()))
    print("🚀 系統初始化完畢，準備進入監控模式...\n")
    time.sleep(0.5)
    
    while True:
        refresh_pool_v90()
        tw_now = get_now_tw()
        
        if not Config.TEST_MODE:        
                if tw_now.weekday() < 5 and tw_now.time() >= Config.AUTO_SHUTDOWN_TIME:
                  print(f"\n[系統時鐘觸發熄火] 當前台北時間 {tw_now.strftime('%H:%M:%S')} 已達 13:35。")
                  sys.exit(0)
        else: 
            print(f"[測試模式] 當前台北時間 {tw_now.strftime('%H:%M:%S')}")   

        # 🌟 監控週期時間戳直覺化
        timer_str = tw_now.strftime('%Y-%m-%d %H:%M:%S')
        print(f"\n[監控週期: {timer_str}]")
        print(f"{wide_ljust('股號股名', 20)} | {wide_ljust('市場', 6)} | {wide_ljust('現價', 10)} | {wide_ljust('量比', 8)} | {wide_ljust('3K高', 10)} | {wide_ljust('3K低', 10)} | 產業別")
        print("-" * 115)
        
        sorted_sids = sorted(stock_info_map.keys(), key=lambda x: 0 if stock_info_map[x]['market'] == '權證' else (1 if stock_info_map[x]['market'] == '上市' else 2))
        passed_min = (datetime.combine(tw_now.date(), tw_now.time()) - datetime.combine(tw_now.date(), Config.MARKET_OPEN)).total_seconds() / 60
        if passed_min <= 0 or passed_min > 270: passed_min = 270.0
            
        max_results = fetch_mis_batch_all()
        mis_ok = len(max_results) > 0
        if mis_ok: print(f"[快速層] MIS 實時雷達運作正常，已捕獲 {len(max_results)} 檔最新行情")

        for sid in sorted_sids:
            info, data = stock_info_map[sid], monitor_data[sid]
            try:
                lp, v, up_pct = None, 0, 0.0
                is_warrant = (info.get('market') == '權證')

                if is_warrant:
                    f_url = f"https://api.fugle.tw/marketdata/v1.0/stock/intraday/quote/{sid}"
                    res = standard_requests.get(f_url, headers={"X-API-KEY": Config.FUGLE_API_KEY.strip()}, timeout=5).json()
                    if res and 'lastPrice' in res and res['lastPrice'] is not None:
                        lp = res.get('lastPrice')
                        v = safe_cast(res.get('total', {}).get('tradeVolume'), int)   
                        ask_vol = sum(safe_cast(a.get('volume', 0), int) for a in res.get('asks', [])[:3])
                        if ask_vol > 0: data['last_consumption'] = min(1.0, v / (ask_vol * 10))
                        
                        # 富果沒有直接提供 up_pct，簡單計算
                        y = safe_cast(res.get('previousClose', '0'), float)
                        if y > 0: up_pct = round((lp - y) / y * 100, 2)
                        data['last_up_pct'] = up_pct
                else:
                    if mis_ok and sid in max_results:
                        m = max_results[sid]
                        lp, v = m['lp'], m['v']
                        up_pct = m.get('up_pct', 0.0)
                        if m.get('ask3', 0) > 0: data['last_consumption'] = min(1.0, v / (m['ask3'] * 10))
                        data['last_up_pct'] = up_pct

                if not lp: continue
                
                if tw_now.time() <= Config.RECOVERY_THRESHOLD:
                    if lp > data['high']: data['high'] = lp
                    if lp < data['low'] or data['low'] == 9999.0: data['low'] = lp
                else:
                    if data['high'] == 0.0: data['high'] = round(lp * 1.02, 2)
                    if data['low'] == 9999.0: data['low'] = round(lp * 0.97, 2)
                
                if 'history_prices' not in data: data['history_prices'] = []
                data['history_prices'].append(lp)
                if len(data['history_prices']) > 5: data['history_prices'].pop(0)
                data['is_accelerating'] = data['history_prices'][-1] > data['history_prices'][-2] if len(data['history_prices']) >= 2 else False
                
                ratio = round((v * (270 / passed_min)) / data['y_vol'], 2) if data['y_vol'] > 0 else 0
                data['last_ratio'] = ratio

                label = f"{sid} {info['name']}"
                print(f"{wide_ljust(label, 20)} | {wide_ljust(info['market'], 6)} | {wide_ljust(lp, 10)} | {wide_ljust(ratio, 8)} | {wide_ljust(data['high'], 10)} | {wide_ljust(data['low'], 10)} | {info['industry']}")

                # 🎯 全策略判定與降噪防擾機制
                is_3k_break = lp > data['high'] > 0
                is_vol_anomaly = ratio >= Config.VOL_EST_THRESHOLD

                # 🎯 策略四：N字突破 (保留發報，並帶入 up_pct 進行漲停阻斷)
                if data['state'] == 1 and lp >= data['point_a'] and data['point_b'] != 9999.0:
                    if not data.get('trig_策略四') and is_vol_anomaly:
                        send_tg_alert(sid, "策略四：N字突破 (洗盤結束再發動)", lp, data['high'], data['low'], ratio, up_pct)
                        data['trig_策略四'] = True
                    data['point_a'], data['point_b'], data['state'] = lp, 9999.0, 0
                elif lp > data['point_a']: data['point_a'], data['point_b'], data['state'] = lp, 9999.0, 1
                elif data['state'] == 1 and lp < data['point_a']:
                    data['point_b'] = min(data['point_b'], lp)
                    if lp < (data['point_a'] + data['high']) / 2: data['state'] = 0

                # 🎯 策略二：3K突破 + 量能異常 (保留發報，並帶入 up_pct 進行漲停阻斷)
                if is_3k_break and is_vol_anomaly and not data.get('trig_both'):
                    send_tg_alert(sid, "🔥 策略二：3K突破 + 量能異常 (價量齊揚)", lp, data['high'], data['low'], ratio, up_pct)
                    data['trig_both'] = data['trig_3k'] = data['trig_vol'] = True
                
                # 🎯 策略一：純 3K 法突破 (僅底層更新狀態機，絕對隱藏不發 TG 警報)
                elif is_3k_break and not data.get('trig_3k'):
                    data['trig_3k'] = True

                if is_warrant: time.sleep(Config.API_THROTTLE_SLEEP)
            except: pass

        # ============================================================
        # 🐢 慢速層 Fugle 精確五檔分析看板一體化日誌更新
        # ============================================================
        if time.time() - _last_fugle_scan >= 60 and len(stock_info_map) > 0:
            warrant_sids = [s for s in stock_info_map if stock_info_map[s].get('is_protected') and stock_info_map[s].get('market') == '權證']
            if warrant_sids:
                print(f"\n[慢速層] 啟動 Fugle 實時精確五檔掛單分析 ({len(warrant_sids)} 檔)...")
                for sid in warrant_sids:
                    try:
                        f_url = f"https://api.fugle.tw/marketdata/v1.0/stock/intraday/quote/{sid}"
                        res = standard_requests.get(f_url, headers={"X-API-KEY": Config.FUGLE_API_KEY.strip()}, timeout=5).json()
                        if res and 'lastPrice' in res and res['lastPrice'] is not None:
                            ask_vol = sum(safe_cast(a.get('volume', 0), int) for a in res.get('asks', [])[:3])
                            v_fugle = safe_cast(res.get('total', {}).get('tradeVolume'), int)
                            if ask_vol > 0: monitor_data[sid]['last_consumption'] = min(1.0, v_fugle / (ask_vol * 10))
                        w_lp = monitor_data[sid].get('history_prices', [100.0])[-1]
                        print(f"{wide_ljust(f'{sid} {stock_info_map[sid]['name']}', 20)} | {wide_ljust('權證', 6)} | {wide_ljust(w_lp, 10)} | {wide_ljust(monitor_data[sid].get('last_ratio', 1.0), 8)} | {wide_ljust(monitor_data[sid]['high'], 10)} | {wide_ljust(monitor_data[sid]['low'], 10)} | {stock_info_map[sid]['industry']}")
                    except: pass
                    time.sleep(Config.API_THROTTLE_SLEEP)
                _last_fugle_scan = time.time()
                print("")
        print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print(f"[時段提示] 方案C 兩層架構穩定運行 (MIS {len(max_results)} 檔)。5秒後刷新...")
        time.sleep(5)

if __name__ == "__main__": main()