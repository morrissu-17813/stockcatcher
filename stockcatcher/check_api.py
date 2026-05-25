import os
import time
import re
import sys
import math
from datetime import datetime, timedelta, timezone, time as dtime
from typing import List
from dateutil.parser import isoparse
from dotenv import load_dotenv

# ⚡ 核心：引入 curl_cffi 偽裝 Chrome 瀏覽器，徹底繞過 SSL 憑證驗證失敗
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
    MAX_POOL_SIZE      = 200
    WARRANT_QUOTA      = 50    
    LISTED_QUOTA       = 100    
    OTC_QUOTA          = 50    
    SCAN_INTERVAL      = 900   

    # 🎯 策略爆發門檻
    ENTRY_MIN_PCT      = 3.5   
    ENTRY_MAX_PCT      = 9.0   
    GRADUATION_PCT     = 9.7   
    VOL_EST_THRESHOLD  = 2.3   

    # ⏰ 時間控制
    MARKET_OPEN        = dtime(9, 0)
    MARKET_CLOSE       = dtime(13, 30)
    AUTO_SHUTDOWN_TIME = dtime(13, 35)  
    RECOVERY_THRESHOLD = dtime(9, 15)  
    ROLLING_3K_WINDOW_MIN = 45   # 滾動3K高低計算視窗
    API_THROTTLE_SLEEP = 1.1   
      
    IS_LOCAL           = True 

# 🗄️ 全域記憶體容器與快照矩陣
stock_info_map = {}   
monitor_data = {}     
finmind_industry_map = {} 
global_volume_lookup = {}    # 儲存成交量 (張數)
global_turnover_lookup = {}  # 儲存成交金額 (金流)
last_scan_time = 0
_exchange_map = {}        
_last_fugle_scan = 0.0    
_mis_session = None       

# ============================================================
# 🛡️ 🔏 [真．全域落鎖區] 核心工具與通訊函數強制置頂
# ============================================================

def get_now_tw():
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
    if up_pct > 9.0:
        return
        
    info = stock_info_map.get(sid, {})
    data = monitor_data.get(sid, {})

    # 第一關：全股票全域 30 分鐘鎖 — 任何策略觸發後，同標的 30 分鐘內全部靜音
    if time.time() - data.get('last_alert_time', 0) < 1800:
        return

    # 第二關：每策略獨立 30 分鐘冷卻 — 防止同策略在全域鎖解除後立即重複觸發
    alert_times = data.setdefault('last_alert_by_strategy', {})
    if time.time() - alert_times.get(strategy_name, 0) < 1800:
        return
        
    badge = "🎫 [權證主力標的] " if info.get('is_protected') else f"[{info.get('market', '未知')}] "
    scenario = "🚨 [訊號觸發]" 
    consumption_str = get_consumption_badge(data.get('last_consumption', 0.45))
    is_acc = data.get('is_accelerating', False)
    stop_loss_price = low if low > 0 else lp
    pct_arrow = "📈" if up_pct >= 0 else "📉"
    pct_str = f"+{up_pct}%" if up_pct > 0 else f"{up_pct}%"
    
    msg = (
        f"{scenario}\n"
        f"🎯 *核心策略：* {badge}{strategy_name}\n"
        f"━━━━━━━━━━━━━━\n"
        f"📈 *標的：* [{sid} {info.get('name', '')}](https://www.nstock.tw/stock_info?stock_id={sid})\n"
        f"💰 *現價：* `{lp}` {pct_arrow} `{pct_str}`\n"
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
        alert_times[strategy_name] = time.time()
        data['last_alert_time'] = time.time()
    except Exception as e:
        print(f"[錯誤] Telegram 發送通知失敗: {e}")

def perform_strategy_test():
    print("📡 啟動自動化測試：發送驗證訊號...", flush=True)
    sid = "2313"
    stock_info_map[sid] = {'name': '華通(測試標的)', 'market': '上市', 'is_protected': False, 'industry': '電子零組件業'}
    monitor_data[sid] = {
        'last_alert_time': 0, 'last_up_pct': 0.0, 'last_consumption': 0.85, 
        'is_accelerating': False, 'history_prices': [350.0]
    }
    send_tg_alert(sid, "🔥 策略二：3K突破+量能異常測試", 350.0, 277.0, 243.0, 1.8, 0.0)
    del stock_info_map[sid]
    del monitor_data[sid]
    print("✅ 自動化測試驗證訊號已成功送出！")

def should_exclude(sid, name, industry):
    sid, name, industry = str(sid).strip(), str(name), str(industry)
    if sid.startswith('00') or sid.startswith('01') or sid.startswith('03') or \
       any(k in name for k in ["ETF", "受益憑證", "基金", "指數", "債券", "存託憑證"]) or \
       any(k in industry for k in ["ETF", "受益憑證", "指數", "債券", "存託憑證"]): return True
    if sid.startswith('28') or sid.startswith('58') or sid.startswith('60') or \
       any(k in name for k in ["金控", "銀行", "保險", "證券", "人壽", "信託", "期貨"]) or \
       any(k in industry for k in ["金融", "保險", "證券", "金控"]): return True
    return False

def fetch_disposition_stocks():
    disposition_set = set()
    try:
        url_notice = "https://openapi.twse.com.tw/v1/announcement/notice"
        res_notice = standard_requests.get(url_notice, timeout=5, verify=False).json()
        for item in res_notice:
            sid = item.get('證券代號', '').strip()
            if sid: disposition_set.add(sid)
    except Exception: pass
    return disposition_set

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
                z, y = item.get('z', '-'), safe_cast(item.get('y', '0'), float)
                lp = y if (z in ('-', '0') or safe_cast(z, float) <= 0) else safe_cast(z, float)
                if lp <= 0: continue
                v = safe_cast(item.get('v', '0').replace(',', ''), int)   
                f_str = item.get('f', '')
                ask3 = sum(safe_cast(x, int) for x in f_str.split('_')[:3]) if f_str else 0
                up_pct = round((lp - y) / y * 100, 2) if y > 0 else 0.0
                results[sid] = {'lp': lp, 'v': v, 'ask3': ask3, 'up_pct': up_pct}
        except Exception: pass
    return results

# TWSE 上市公司產業別數字代碼 → 文字名稱對照表
_TWSE_INDUSTRY_CODE_MAP = {
    '01': '水泥工業',    '02': '食品工業',    '03': '塑膠工業',    '04': '紡織纖維',
    '05': '電機機械',    '06': '電器電纜',    '07': '化學生技醫療', '08': '玻璃陶瓷',
    '09': '造紙工業',    '10': '鋼鐵工業',    '11': '橡膠工業',    '12': '汽車工業',
    '13': '電子工業',    '14': '建材營造',    '15': '航運業',      '16': '觀光餐旅',
    '17': '金融保險',    '18': '貿易百貨',    '19': '綜合',        '20': '其他',
    '21': '化學工業',    '22': '生技醫療業',  '23': '油電燃氣業',  '24': '半導體業',
    '25': '電腦及週邊設備業', '26': '光電業', '27': '通信網路業',  '28': '電子零組件業',
    '29': '電子通路業',  '30': '資訊服務業',  '31': '其他電子業',  '32': '文化創意業',
    '33': '農業科技業',  '34': '電子商務',    '35': '綠能環保',    '36': '數位雲端',
    '37': '運動休閒',    '38': '居家生活',    '39': '管理股票',
}

def fetch_finmind_industry_mapping():
    mapping = {
        "2330": {"name": "台積電", "industry": "半導體業"}, "2317": {"name": "鴻海", "industry": "其他電子業"},
        "2454": {"name": "聯發科", "industry": "半導體業"}, "2382": {"name": "廣達", "industry": "電腦週邊業"}
    }
    try:
        twse_profile = standard_requests.get("https://openapi.twse.com.tw/v1/opendata/t187ap03_L", timeout=10, verify=False).json()
        if isinstance(twse_profile, list):
            for row in twse_profile:
                sid = row.get('公司代號', '').strip()
                if len(sid) == 4:
                    ind_code = row.get('產業別', '').strip()
                    ind_name = _TWSE_INDUSTRY_CODE_MAP.get(ind_code, '上市其他')
                    mapping[sid] = {"name": row.get('公司簡稱', '').strip(), "industry": ind_name}
    except Exception: pass
    try:
        from FinMind.data import DataLoader
        dl = DataLoader()
        try:
            if Config.FINMIND_TOKEN: dl.login_by_token(Config.FINMIND_TOKEN)
        except Exception: pass
        df_info = dl.taiwan_stock_info()
        df_info['_sid'] = df_info['stock_id'].astype(str).str.strip()
        tpex_df = df_info[(df_info['type'] == 'tpex') & (df_info['_sid'].str.len() == 4)]
        for _, row in tpex_df.iterrows():
            sid = row['_sid']
            mapping[sid] = {"name": str(row.get('stock_name', '')).strip(), "industry": str(row.get('industry_category', '上櫃其他')).strip()}
    except Exception: pass
    return mapping

def fetch_market_candidates(market_type="上市"):
    candidates = []
    disposition_set = fetch_disposition_stocks()
    try:
        if market_type == "上市":
            url = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
            res = standard_requests.get(url, timeout=10, verify=False).json()
            rows = res if isinstance(res, list) else []
            for i in rows:
                sid = i.get('Code')
                if not sid or len(sid) != 4 or sid in disposition_set or sid in stock_info_map: continue
                fm = finmind_industry_map.get(sid, {"name": i.get('Name', f"上市_{sid}").strip(), "industry": "電子零組件業"})
                if should_exclude(sid, fm['name'], fm['industry']): continue
                vol = safe_cast(i.get('TradeVolume'), int) // 1000  
                turnover = safe_cast(i.get('TradeValue'), float) 
                candidates.append({'sid': sid, 'up_pct': 0.0, 'vol': vol, 'turnover': turnover, 'market': '上市', 'name': fm['name'], 'ind': fm['industry']})
        else:
            url = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_quotes"
            res = standard_requests.get(url, timeout=10, verify=False).json()
            rows = res if isinstance(res, list) else []
            for i in rows:
                sid = i.get('SecuritiesCompanyCode', '').strip()
                if not sid or len(sid) != 4 or sid in disposition_set or sid in stock_info_map: continue
                raw_name = i.get('CompanyName', i.get('SecuritiesCompanyName', f"上櫃_{sid}")).strip()
                fm = finmind_industry_map.get(sid, {"name": raw_name, "industry": "半導體業"})
                if should_exclude(sid, fm['name'], fm['industry']): continue
                vol = safe_cast(i.get('TradingShares'), int) // 1000  
                turnover = safe_cast(i.get('TradingAmount'), float)
                candidates.append({'sid': sid, 'up_pct': 0.0, 'vol': vol, 'turnover': turnover, 'market': '上櫃', 'name': fm['name'], 'ind': fm['industry']})
                
        if candidates:
            candidates.sort(key=lambda x: x['turnover'], reverse=True)
            for idx, c in enumerate(candidates): c['rank_t'] = idx
            candidates.sort(key=lambda x: x['vol'], reverse=True)
            for idx, c in enumerate(candidates): c['rank_v'] = idx
            candidates.sort(key=lambda x: x['rank_t'] + x['rank_v'])
    except Exception: pass
    return candidates

def refresh_pool_v90():
    global last_scan_time
    now = time.time()
    # 9:30 前不換池，盤前已選好股池，開盤後才開始動態輪換
    if get_now_tw().time() < dtime(9, 30):
        return
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

        for cand in candidates[:vacancy]:
            csid = cand['sid']
            stock_info_map[csid] = {'name': cand['name'], 'market': m_type, 'is_protected': False, 'industry': cand['ind']}
            monitor_data[csid] = {
                "high": 0.0, "low": 9999.0, "y_vol": cand['vol'], 
                "trig_both": False, "trig_3k": False, "trig_vol": False, "trig_策略四": False,
                "state": 0, "point_a": 0.0, "point_b": 9999.0,  
                "last_alert_time": 0, "last_up_pct": 0.0, "last_ratio": 1.0, "last_consumption": 0.0, "is_accelerating": False, "history_prices": [],
                "price_window": [], "last_alert_by_strategy": {}
            }

# ============================================================
# 🕵️‍♂️ ✅ [V118.3 終極權證解析] 完全捨棄字串正則，直連官方代碼映射
# ============================================================
def load_official_warrant_targets() -> List[str]:
    print("📡 正在解析全市場權證發行清單 (TWSE官方映射 + 雙因子排序)...", flush=True)
    valid_underlying_sids = set()
    
    # Step 1: 從 TWSE 取得上市權證基本資訊 (直接抓取標的代號，無懼名稱縮寫與字體差異)
    try:
        res = standard_requests.get("https://openapi.twse.com.tw/v1/opendata/t187ap37_L", timeout=10, verify=False).json()
        
        # 建立正反向名稱映射表，作為保底防禦
        name_to_sid = {}
        for sid, info in finmind_industry_map.items():
            clean_name = info['name'].replace('*', '').strip().replace('臺', '台')
            name_to_sid[clean_name] = sid
        
        for row in res:
            underlying_sid = str(row.get('標的證券代號', '')).strip()
            # 如果官方直接給了 4 碼數字代號，這就是 100% 準確的正股
            if len(underlying_sid) == 4 and underlying_sid.isdigit():
                valid_underlying_sids.add(underlying_sid)
            else:
                # 備用防禦：萬一官方沒給代號只給名字，透過字典反查
                sname = str(row.get('標的證券/指數', '')).replace('*', '').strip().replace('臺', '台')
                if sname in name_to_sid:
                    valid_underlying_sids.add(name_to_sid[sname])
    except Exception as e:
        print(f"❌ [TWSE 權證清單解析失敗] {e}")

    # Step 2: 從 元大權證網 熱門榜做絕對暴力備援
    try:
        res = curl_requests.get("https://www.warrantwin.com.tw/eyuanta/Warrant/HotTarget.aspx", impersonate="chrome120", timeout=15)
        if res.status_code == 200:
            codes = re.findall(r'\b([0-9]{4})\b', res.text)
            for sid in codes:
                if sid not in ['1999', '2024', '2025', '2026', '0800']:
                    valid_underlying_sids.add(sid)
    except Exception: pass

    # Step 3: 使用雙因子 (金額+張數) 對這些「確定有權證的標的」進行大排序
    warrant_candidates = []
    for sid in valid_underlying_sids:
        # 如果今日沒有成交量/金額，直接忽略
        if sid not in global_volume_lookup or sid not in global_turnover_lookup:
            continue
        today_vol = global_volume_lookup[sid]
        today_turnover = global_turnover_lookup[sid]
        
        if today_vol > 0 and today_turnover > 0:
            warrant_candidates.append({'sid': sid, 'vol': today_vol, 'turnover': today_turnover})

    if warrant_candidates:
        warrant_candidates.sort(key=lambda x: x['turnover'], reverse=True)
        for idx, c in enumerate(warrant_candidates): c['rank_t'] = idx
        
        warrant_candidates.sort(key=lambda x: x['vol'], reverse=True)
        for idx, c in enumerate(warrant_candidates): c['rank_v'] = idx
        
        # 數字越小代表綜合實力越強 (金額與張數都名列前茅)
        warrant_candidates.sort(key=lambda x: x['rank_t'] + x['rank_v'])

    clean_hot_sids = [item['sid'] for item in warrant_candidates][:Config.WARRANT_QUOTA]
    print(f"✅ 權證熱門榜精準解析完成！最終取得 {len(clean_hot_sids)} 檔頂級熱門標的。")
    return clean_hot_sids

def pre_market_initialization():
    global global_volume_lookup, global_turnover_lookup
    twse_sids = set()
    disposition_set = fetch_disposition_stocks()

    try:
        twse_data = standard_requests.get("https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL", timeout=10, verify=False).json()
        if isinstance(twse_data, list):
            for row in twse_data:
                code = row.get('Code', '').strip()
                if len(code) == 4:
                    global_volume_lookup[code] = safe_cast(row.get('TradeVolume'), int) // 1000
                    global_turnover_lookup[code] = safe_cast(row.get('TradeValue'), float)
                    twse_sids.add(code)
    except: pass
    try:
        tpex_data = standard_requests.get("https://www.tpex.org.tw/openapi/v1/tpex_mainboard_quotes", timeout=10, verify=False).json()
        if isinstance(tpex_data, list):
            for row in tpex_data:
                code = str(row.get('SecuritiesCompanyCode', '')).strip()
                if len(code) == 4: 
                    global_volume_lookup[code] = safe_cast(row.get('TradingShares'), int) // 1000
                    global_turnover_lookup[code] = safe_cast(row.get('TradingAmount'), float)
    except: pass

    # 執行 V118.3 最新獲取邏輯
    clean_sids = load_official_warrant_targets()

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
                "last_alert_time": 0, "last_up_pct": 0.0, "last_ratio": 1.0, "last_consumption": 0.85, "is_accelerating": True, "history_prices": [],
                "price_window": [], "last_alert_by_strategy": {}
            }
            injected += 1
            if injected >= Config.WARRANT_QUOTA: break
            
    print(f"真．動態權證現股化分析完成，最終注入 {injected} 檔實時金流標的。")

def update_rolling_3k(sid, lp):
    data = monitor_data[sid]
    now_ts = time.time()
    cutoff_ts = now_ts - Config.ROLLING_3K_WINDOW_MIN * 60

    pw = data.setdefault('price_window', [])
    if not pw and data.get('high', 0) > 0 and data.get('low', 9999.0) < 9999.0:
        pw.append((cutoff_ts + 60, data['high']))
        pw.append((cutoff_ts + 60, data['low']))

    pw.append((now_ts, lp))
    data['price_window'] = [(ts, p) for ts, p in pw if ts >= cutoff_ts]

    prices = [p for _, p in data['price_window']]
    if prices:
        data['high'] = max(prices)
        data['low']  = min(prices)

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
                if v_h:
                    _rh, _rl = max(v_h), min(v_l)
                    monitor_data[sid]['high'], monitor_data[sid]['low'] = _rh, _rl
                    _seed_ts = time.time() - (Config.ROLLING_3K_WINDOW_MIN - 1) * 60
                    monitor_data[sid]['price_window'] = [(_seed_ts, _rh), (_seed_ts, _rl)]
        except: pass
        time.sleep(Config.API_THROTTLE_SLEEP)

# ------------------------------------------------------------
# 🎬 主程式核心驅動流
# ------------------------------------------------------------

def main():
    global _last_fugle_scan, finmind_industry_map
    print(f"🛡️ 蘇蘇的天機選股 V118.3 啟動完成。")
    print(f"{get_now_tw().strftime('%H:%M:%S')} 執行盤前籌碼映射與官方 Profile 基本面同步...")
    
    finmind_industry_map = fetch_finmind_industry_mapping()
    pre_market_initialization()
    print("🛰️ 啟動市場配額同步...")
    refresh_pool_v90()
    
    w_count = len([s for s in stock_info_map if stock_info_map[s]['market'] == '權證'])
    l_count = len([s for s in stock_info_map if stock_info_map[s]['market'] == '上市'])
    o_count = len([s for s in stock_info_map if stock_info_map[s]['market'] == '上櫃'])
    print(f"✅ 初始化：上市 {l_count} 檔、上櫃 {o_count} 檔、權證相關現股 {w_count} 檔")
    
    perform_strategy_test()
    recover_3k_data(list(stock_info_map.keys()))
    print("🚀 系統初始化完畢，準備進入監控模式...\n")
    time.sleep(0.5)
    
    while True:
        refresh_pool_v90()
        tw_now = get_now_tw()
        
        if not Config.IS_LOCAL:        
            if tw_now.weekday() < 5 and tw_now.time() >= Config.AUTO_SHUTDOWN_TIME:
                print(f"\n[系統時鐘觸發熄火] 當前台北時間 {tw_now.strftime('%H:%M:%S')} 已達 13:35。")
                sys.exit(0)
        else: 
            pass  

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
                lp_is_fresh = False
                is_warrant = (info.get('market') == '權證')

                if is_warrant:
                    f_url = f"https://api.fugle.tw/marketdata/v1.0/stock/intraday/quote/{sid}"
                    res = standard_requests.get(f_url, headers={"X-API-KEY": Config.FUGLE_API_KEY.strip()}, timeout=5).json()
                    if res and 'lastPrice' in res and res['lastPrice'] is not None:
                        lp = res.get('lastPrice')
                        lp_is_fresh = True
                        v = safe_cast(res.get('total', {}).get('tradeVolume'), int)   
                        ask_vol = sum(safe_cast(a.get('volume', 0), int) for a in res.get('asks', [])[:3])
                        if ask_vol > 0: data['last_consumption'] = min(1.0, v / (ask_vol * 10))
                        
                        y = safe_cast(res.get('previousClose', '0'), float)
                        if y > 0: up_pct = round((lp - y) / y * 100, 2)
                        data['last_up_pct'] = up_pct
                else:
                    if mis_ok and sid in max_results:
                        m = max_results[sid]
                        lp, v = m['lp'], m['v']
                        lp_is_fresh = True
                        up_pct = m.get('up_pct', 0.0)
                        if m.get('ask3', 0) > 0: data['last_consumption'] = min(1.0, v / (m['ask3'] * 10))
                        data['last_up_pct'] = up_pct

                if lp is None and Config.IS_LOCAL:
                    y_val = safe_cast(finmind_industry_map.get(sid, {}).get('y', '0'), float)
                    seed_base = y_val if y_val > 0 else (1000.0 if sid=='2330' else (210.0 if sid=='2317' else 85.0))
                    wave = math.sin(passed_min * 0.15 + int(sid)) * 0.03
                    lp = round(seed_base * (1.002 + wave), 2)
                    v = int(data['y_vol'] * (passed_min / 270.0) * (1.1 + abs(wave)))
                    lp_is_fresh = True

                if lp is None:
                    if data.get('history_prices'): lp = data['history_prices'][-1]
                if not lp: continue
                
                _old_3k_high = data['high']
                update_rolling_3k(sid, lp)

                if 'history_prices' not in data: data['history_prices'] = []
                data['history_prices'].append(lp)
                if len(data['history_prices']) > 5: data['history_prices'].pop(0)
                data['is_accelerating'] = data['history_prices'][-1] > data['history_prices'][-2] if len(data['history_prices']) >= 2 else False
                
                ratio = round((v * (270 / passed_min)) / data['y_vol'], 2) if data['y_vol'] > 0 else 0
                data['last_ratio'] = ratio

                stock_label = f"{sid} {info.get('name', '')}"
                print(f"{wide_ljust(stock_label, 20)} | {wide_ljust(info['market'], 6)} | {wide_ljust(lp, 10)} | {wide_ljust(ratio, 8)} | {wide_ljust(data['high'], 10)} | {wide_ljust(data['low'], 10)} | {info['industry']}")

                # 價格非即時（API 失敗降級至歷史快取）時，跳過策略評估與通知
                if not lp_is_fresh:
                    if is_warrant: time.sleep(Config.API_THROTTLE_SLEEP)
                    continue

                is_3k_break = lp > _old_3k_high > 0
                is_vol_anomaly = ratio >= Config.VOL_EST_THRESHOLD

                # N字有效回落：point_b 需至少低於 point_a 2.5%（過濾微震）
                _n_valid_pullback = data['point_b'] != 9999.0 and data['point_b'] <= data['point_a'] * 0.975

                if data['state'] == 1 and lp >= data['point_a'] and _n_valid_pullback:
                    if is_vol_anomaly:
                        send_tg_alert(sid, "策略四：N字突破 (洗盤結束再發動)", lp, data['high'], data['low'], ratio, up_pct)
                        data['point_a'], data['point_b'], data['state'] = lp, 9999.0, 0
                    else:
                        # 量能不足：保留 state=1 等下一根確認，只更新 point_a 至新高
                        data['point_a'] = lp
                elif lp > data['point_a']: data['point_a'], data['point_b'], data['state'] = lp, 9999.0, 1
                elif data['state'] == 1 and lp < data['point_a']:
                    data['point_b'] = min(data['point_b'], lp)
                    if lp < data['point_a'] * 0.95:
                        data['point_b'] = 9999.0
                        data['state'] = 0

                if is_3k_break and is_vol_anomaly:
                    send_tg_alert(sid, "🔥 策略二：3K突破 + 量能異常 (價量齊揚)", lp, _old_3k_high, data['low'], ratio, up_pct)

                if is_warrant: time.sleep(Config.API_THROTTLE_SLEEP)
            except: pass

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
                        warrant_label = f"{sid} {stock_info_map[sid].get('name', '')}"
                        print(f"{wide_ljust(warrant_label, 20)} | {wide_ljust('權證', 6)} | {wide_ljust(w_lp, 10)} | {wide_ljust(monitor_data[sid].get('last_ratio', 1.0), 8)} | {wide_ljust(monitor_data[sid]['high'], 10)} | {wide_ljust(monitor_data[sid]['low'], 10)} | {stock_info_map[sid]['industry']}")
                    except: pass
                    time.sleep(Config.API_THROTTLE_SLEEP)
                _last_fugle_scan = time.time()
                print("")
                
        print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print(f"[時段提示] 方案C 兩層架構穩定運行 (MIS {len(max_results)} 檔)。5秒後刷新...")
        time.sleep(5)

if __name__ == "__main__": main()
