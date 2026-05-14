import os
import time
import requests
import urllib3
from datetime import datetime, timedelta, timezone, time as dtime
from dotenv import load_dotenv

# 🛡️ 蘇蘇的開發規範：禁用不安全請求警告，載入環境變數防止憑證硬編碼
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
load_dotenv()

# ============================================================
# ⚙️ [系統配置區]
# ============================================================
class Config:
    """
    全域配置中心。
    配額分配：20 權證/保底 + 90 上市動態 + 30 上櫃動態 = 140 檔。
    """
    FUGLE_API_KEY = os.getenv("FUGLE_API_KEY")
    TELEGRAM_TOKEN ="8480482512:AAGin83kwa61oa5F5rBj4NQMow-C9jsbJug"
    TELEGRAM_CHAT_ID ="1087480334"

    # 📊 嚴格配額管理
    MAX_POOL_SIZE    = 140
    WARRANT_QUOTA    = 20    # 權證與籌碼保底 (is_protected)
    LISTED_QUOTA     = 90    # 上市動態名額 (TWSE)
    OTC_QUOTA        = 30    # 上櫃動態名額 (TPEx)
    SCAN_INTERVAL    = 900   # 全市場掃描頻率 (15 分鐘)

    # 🎯 策略門檻
    ENTRY_MIN_PCT     = 3.5   # 黃金跑道起點 (也是重置門檻)
    ENTRY_MAX_PCT     = 9.0   # 黃金跑道終點
    GRADUATION_PCT    = 9.7   # 畢業門檻 (接近漲停則移除名額)
    STRATEGY_2_RATIO  = 3.0   # 策略二：量能異常比門檻 (主迴圈使用)
    VOL_EST_THRESHOLD = 1.6   # 量能比觸發門檻 (測試框架 / 盤中監控使用)

    # ⏰ 時間與冷卻設定
    MARKET_OPEN      = dtime(9, 0)
    MARKET_CLOSE     = dtime(13, 30)
    VOL_CHECK_START  = dtime(9, 30)  # 量能異常開始監控時間（開盤前 30 分鐘過濾雜訊）
    ALERT_COOLDOWN   = 600   # 發報冷卻時間 (10 分鐘)

    API_THROTTLE     = 1.1   # 遵循 Fugle API 頻率限制

# 🗄️ 全域記憶體容器
stock_info_map = {}   # { sid: { name, market, is_protected } }
monitor_data = {}     # { sid: { 技術指標與狀態機數據 } }
last_scan_time = 0

# ------------------------------------------------------------
# 🛠️ 輔助工具模組 (最佳實踐)
# ------------------------------------------------------------

def get_tick_size(price: float, market_type: str = "上市") -> float:
    """
    計算台股升降單位 (Tick Size)。
    特別注意：權證在 10~50 元區間的一檔為 0.1，與股票的 0.05 不同。
    """
    if market_type == "權證":
        if price < 5: return 0.01
        if price < 10: return 0.05
        if price < 50: return 0.1
        if price < 100: return 0.5
        if price < 500: return 1.0
        return 5.0
    else: # 上市與上櫃股票
        if price < 10: return 0.01
        if price < 50: return 0.05
        if price < 100: return 0.1
        if price < 500: return 0.5
        if price < 1000: return 1.0
        return 5.0

def get_consumption_badge(rate: float) -> str:
    """ 壓力消化率視覺化標籤 🟢🟡🔴 """
    pct = int(rate * 100)
    if pct >= 80: return f"🟢 {pct}%"
    if pct >= 40: return f"🟡 {pct}%"
    return f"🔴 {pct}%"

def get_tw_now():
    """ 取得台灣標準時間 (UTC+8) """
    return datetime.now(timezone.utc) + timedelta(hours=8)

def safe_cast(value, target_type, default=0):
    """
    安全型別轉換。支援含逗號字串、None、空字串、NaN 等邊界情況。
    範例：safe_cast("15,000", int) → 15000
          safe_cast(None, int, 0) → 0
    """
    import math
    if value is None:
        return default
    try:
        str_val = str(value).replace(',', '').strip()
        if not str_val:
            return default
        f = float(str_val)
        if math.isnan(f):
            return default
        return target_type(f)
    except (ValueError, TypeError):
        return default

# ------------------------------------------------------------
# 📈 通訊發報模組
# ------------------------------------------------------------

def send_telegram_alert(sid, strategy_name, lp, reason_type="A"):
    """
    發送結構化策略告警。
    A: 正式觸發策略；B: 盤口先機預判。
    """
    info = stock_info_map.get(sid, {})
    data = monitor_data.get(sid, {})
    
    badge = "🎫 [核心保底] " if info.get('market') == '權證' or info.get('is_protected') else f"[{info.get('market')}] "
    scenario = "🚨 [天機正式觸發]" if reason_type == "A" else "👀 [天機預警-觀察蓄勢]"
    consumption_str = get_consumption_badge(data.get('last_consumption', 0))
    
    msg = (
        f"{scenario}\n"
        f"🎯 *核心策略：* {badge}{strategy_name}\n"
        f"━━━━━━━━━━━━━━\n"
        f"📈 *標的：* {sid} {info.get('name')}\n"
        f"💰 *現價：* `{lp}` (漲幅: {data.get('last_up_pct')}%)\n"
        f"📊 *預估量比：* `{data.get('last_ratio')}x`\n"
        f"💥 *壓力消化：* {consumption_str}\n"
        f"🚀 *能量斜率：* {'陡增' if data.get('is_accelerating') else '平穩'}\n"
        f"━━━━━━━━━━━━━━\n"
        f"⏰ {get_tw_now().strftime('%H:%M:%S')}"
    )
    
    print(f"console.log: [發送通知] {sid} - {strategy_name} ({reason_type})")
    url = f"https://api.telegram.org/bot{Config.TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": Config.TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"}, timeout=5)
        data['last_alert_time'] = time.time()
    except Exception as e:
        print(f"console.log: [錯誤] Telegram API 呼叫失敗: {e}")

def send_tg_alert(sid, strategy, lp, high=0, low=0, ratio=0, reason_type="A"):
    """
    V2 發報函式，含 nstock.tw 深度連結與完整市場資訊。
    供策略觸發時呼叫，明確傳入 3K 高低點與量能比。
    """
    info = stock_info_map.get(sid, {})
    badge = "🎫 [核心保底] " if info.get('is_protected') else f"[{info.get('market', '?')}] "
    scenario = "🚨 [天機正式觸發]" if reason_type == "A" else "👀 [天機預警]"
    msg = (
        f"{scenario}\n"
        f"🎯 *策略：* {badge}{strategy}\n"
        f"━━━━━━━━━━━━━━\n"
        f"📈 *標的：* [{sid} {info.get('name', '')}](https://www.nstock.tw/stock_info?ac={sid})\n"
        f"💰 *現價：* `{lp}` | 3K高: `{high}` | 3K低: `{low}`\n"
        f"📊 *量能比：* `{ratio}x`\n"
        f"🏭 *產業：* {info.get('industry', 'N/A')}\n"
        f"━━━━━━━━━━━━━━\n"
        f"⏰ {get_tw_now().strftime('%H:%M:%S')}"
    )
    url = f"https://api.telegram.org/bot{Config.TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": Config.TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"}, timeout=5)
    except Exception as e:
        print(f"console.log: [錯誤] Telegram 發送失敗: {e}")

# ------------------------------------------------------------
# 🔄 汰換引擎 (V90.6 雙市場分流)
# ------------------------------------------------------------

def fetch_market_candidates(market_type="上市"):
    """
    針對上市(TWSE)與上櫃(TPEx)分別請求 OpenAPI 並清洗資料。
    vol 統一換算為「張」(//1000)，與 Fugle tradeVolume 單位一致。

    資料源：
      上市：https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL
      上櫃：https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes
    """
    candidates = []
    try:
        if market_type == "上市":
            url = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
            res = requests.get(url, timeout=10).json()
            for i in res:
                sid = i.get('Code', '').strip()
                if len(sid) != 4 or sid in stock_info_map: continue
                close_str  = i.get('ClosingPrice', '0').replace(',', '').strip()
                change_str = i.get('Change', '').replace(',', '').strip()
                if not change_str or change_str in ('--', 'X0.00', ''): continue
                try:
                    close  = float(close_str)
                    change = float(change_str)
                    ref_p  = close - change
                    up_pct = round((change / ref_p) * 100, 2) if ref_p > 0 else 0
                    vol    = int(i.get('TradeVolume', '0').replace(',', '')) // 1000  # ✅ 股→張
                    if Config.ENTRY_MIN_PCT <= up_pct <= Config.ENTRY_MAX_PCT and vol >= 1000:
                        candidates.append({'sid': sid, 'up_pct': up_pct, 'vol': vol,
                                           'market': '上市', 'name': i.get('Name', '未知')})
                except ValueError: continue

        elif market_type == "上櫃":
            # ✅ 正確的 TPEx OpenAPI v1 端點與欄位名稱
            url = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"
            res = requests.get(url, timeout=10).json()
            for i in res:
                sid = str(i.get('SecuritiesCompanyCode', '')).strip()
                if len(sid) != 4 or sid in stock_info_map: continue
                close_str  = str(i.get('Close', '0')).replace(',', '').strip()
                change_str = str(i.get('Change', '')).replace(',', '').replace('+', '').strip()
                if not change_str or change_str in ('--', ''): continue
                try:
                    close  = float(close_str)
                    change = float(change_str)
                    ref_p  = close - change
                    up_pct = round((change / ref_p) * 100, 2) if ref_p > 0 else 0
                    vol    = int(str(i.get('TradingShares', '0')).replace(',', '')) // 1000  # ✅ 股→張
                    if Config.ENTRY_MIN_PCT <= up_pct <= Config.ENTRY_MAX_PCT and vol >= 500:
                        candidates.append({'sid': sid, 'up_pct': up_pct, 'vol': vol,
                                           'market': '上櫃', 'name': i.get('CompanyName', '未知')})
                except ValueError: continue

    except Exception as e:
        print(f"console.log: [錯誤] {market_type} OpenAPI 請求失敗: {e}")
    return candidates

def refresh_pool_v90():
    """ 
    V90.6 汰換核心：嚴格遵守 90 上市 / 30 上櫃之配額。
    """
    global last_scan_time
    now = time.time()
    if now - last_scan_time < Config.SCAN_INTERVAL: return
    last_scan_time = now
    
    print(f"\n======== 🔄 啟動動態汰換程序 (V90.6 配額管理) ========")
    
    # 分別處理上市與上櫃
    market_configs = [
        {"type": "上市", "quota": Config.LISTED_QUOTA, "fetch_func": lambda: fetch_market_candidates("上市")},
        {"type": "上櫃", "quota": Config.OTC_QUOTA, "fetch_func": lambda: fetch_market_candidates("上櫃")}
    ]

    for config in market_configs:
        m_type = config["type"]
        m_quota = config["quota"]
        
        # 1. 抓取該市場候選人
        candidates = config["fetch_func"]()
        
        # 2. 找出目前池子中屬於該市場且「非保底」的標的
        current_dynamic_sids = [
            s for s in stock_info_map 
            if stock_info_map[s]['market'] == m_type and not stock_info_map[s].get('is_protected')
        ]
        
        # 3. 計算畢業生 (漲幅接近漲停) 與 低活力標的 (排序：漲幅*0.6 + 量比*0.4)
        graduates = [s for s in current_dynamic_sids if monitor_data.get(s, {}).get('last_up_pct', 0) >= Config.GRADUATION_PCT]
        losers = sorted(
            [s for s in current_dynamic_sids if s not in graduates],
            key=lambda x: (monitor_data.get(x, {}).get('last_up_pct', 0)*0.6 + monitor_data.get(x, {}).get('last_ratio', 0)*0.4)
        )
        
        # 4. 執行汰換：若超過配額則移除，並補入候選人
        to_remove_count = max(0, len(current_dynamic_sids) + len(candidates) - m_quota)
        to_remove = (graduates + losers)[:to_remove_count]
        
        for rsid in to_remove:
            print(f"console.log: [移除] {m_type}-{rsid}")
            del stock_info_map[rsid], monitor_data[rsid]

        # 5. 補齊至配額（僅計算動態非保底數量，保底標的不佔動態名額）
        remaining_count = len([
            s for s in stock_info_map
            if stock_info_map[s]['market'] == m_type
            and not stock_info_map[s].get('is_protected')
        ])
        vacancy = m_quota - remaining_count

        for cand in sorted(candidates, key=lambda x: x['up_pct'], reverse=True)[:vacancy]:
            csid = cand['sid']
            stock_info_map[csid] = {'name': cand['name'], 'market': m_type, 'is_protected': False}
            monitor_data[csid] = {
                "high": 0.0, "y_vol": cand['vol'], "state": 0, "point_a": 0.0, "point_b": 9999.0,
                "trig_策略一": False, "trig_策略三": False, "trig_策略四": False, "trig_策略預判": False,
                "last_alert_time": 0, "last_up_pct": cand['up_pct'], "last_ratio": 0.0,
                "last_consumption": 0.0, "history_prices": []  # ✅ 補齊 last_consumption
            }
            print(f"console.log: [入選] {m_type}-{csid} (漲幅: {cand['up_pct']}%)")

# ------------------------------------------------------------
# 🕵️‍♂️ 盤前籌碼模組 (方案 B：每日執行一次)
# ------------------------------------------------------------

def pre_market_initialization(top_warrants=None):
    """
    一次性初始化：權證映射與熱門買超現股保底注入。
    :param top_warrants: Top N 權證代號列表（可由爬蟲或測試注入）。
                         None 時使用預設示例。最多注入 Config.WARRANT_QUOTA 筆。
    """
    print(f"console.log: [08:50] 執行盤前籌碼映射與保底注入...")
    mapping_url = "https://openapi.twse.com.tw/v1/exchangeReport/BWSC7U_ALL"
    underlying_map = {}
    try:
        res = requests.get(mapping_url, timeout=15)
        if res.status_code == 200:
            for item in res.json():
                w_id = item.get('權證代號', '').strip()
                s_id = item.get('標的證券代號', '').strip()
                if w_id and s_id: underlying_map[w_id] = s_id
    except Exception as e:
        print(f"console.log: [警告] 無法取得權證映射資料: {e}"); return

    if top_warrants is None:
        top_warrants = ['70001P', '038822']  # 示例，實際應由爬蟲模組提供

    injected = 0
    for wid in top_warrants:
        if injected >= Config.WARRANT_QUOTA:
            print(f"console.log: [籌碼注入] 已達保底配額上限 {Config.WARRANT_QUOTA} 檔，停止注入。")
            break
        sid = underlying_map.get(wid)
        if not sid:
            continue
        if sid not in stock_info_map:
            # 全新注入
            stock_info_map[sid] = {'name': '權證籌碼核心', 'market': '上市', 'is_protected': True}
            monitor_data[sid] = {
                "high": 0.0, "y_vol": 0, "state": 0, "point_a": 0.0, "point_b": 9999.0,
                "trig_策略一": False, "trig_策略三": False, "trig_策略四": False, "trig_策略預判": False,
                "last_alert_time": 0, "last_up_pct": 0.0, "last_ratio": 0.0,
                "last_consumption": 0.0, "history_prices": []
            }
            injected += 1
            print(f"console.log: [保底鎖定] {sid} ({injected}/{Config.WARRANT_QUOTA})")
        elif not stock_info_map[sid].get('is_protected'):
            # ✅ 重疊升級：已在動態池，原地標記為保底（保留既有 monitor_data）
            stock_info_map[sid]['is_protected'] = True
            injected += 1
            print(f"console.log: [升級保底] {sid} 從動態池升級 ({injected}/{Config.WARRANT_QUOTA})")
    print(f"console.log: [盤前初始化完成] 共注入/升級 {injected} 筆保底標的。")

# ------------------------------------------------------------
# 🎬 監控主迴圈 (V90.6 完全整合)
# ------------------------------------------------------------

def main():
    print(f"🛡️ 蘇蘇的天機選股 V90.6 啟動完成。")
    
    # 1. 執行一次性盤前準備
    pre_market_initialization()
    
    # 2. 監控主迴圈
    while True:
        tw_now = get_tw_now()
        if Config.MARKET_OPEN <= tw_now.time() <= Config.MARKET_CLOSE:
            # 觸發動態汰換
            refresh_pool_v90()
            
            # 分母計算 (開盤經過分鐘)
            elapsed = max(1.0, (datetime.combine(tw_now.date(), tw_now.time()) - datetime.combine(tw_now.date(), Config.MARKET_OPEN)).total_seconds() / 60)

            for sid in list(stock_info_map.keys()):
                try:
                    f_url = f"https://api.fugle.tw/marketdata/v1.0/stock/intraday/quote/{sid}"
                    res = requests.get(f_url, headers={"X-API-KEY": Config.FUGLE_API_KEY}, timeout=5).json()
                    if 'lastPrice' not in res: continue
                    
                    lp = res['lastPrice']; ref_p = res['referencePrice']; vol = res['total']['tradeVolume']; data = monitor_data[sid]
                    
                    # ✅ 核心修正 4.1：突破判定前存快照
                    prev_high = data['high']
                    data['high'] = max(data['high'], res.get('highPrice', lp))
                    data['last_up_pct'] = round(((lp - ref_p) / ref_p) * 100, 2)
                    data['last_ratio'] = round((vol * (270 / elapsed)) / data['y_vol'], 2) if data['y_vol'] > 0 else 0
                    
                    # 壓力消化與能量斜率
                    ask_vol = sum([a['volume'] for a in res.get('asks', [])[:3]]) 
                    data['last_consumption'] = min(1.0, vol / (ask_vol * 10)) if ask_vol > 0 else 0
                    
                    is_突破一 = (lp > prev_high > 0)
                    is_量能二 = (data['last_ratio'] >= Config.STRATEGY_2_RATIO)
                    
                    # ✅ 智能旗標重置 (跌破 3.5% + 10分鐘冷卻)
                    if data['last_up_pct'] < Config.ENTRY_MIN_PCT and (time.time() - data.get('last_alert_time', 0) > Config.ALERT_COOLDOWN):
                        data['trig_策略一'] = data['trig_策略三'] = data['trig_策略四'] = data['trig_策略預判'] = False

                    # 💡 場景 B：權證與保底預判
                    tick = get_tick_size(lp, stock_info_map[sid]['market'])
                    if (stock_info_map[sid].get('market') == '權證' or stock_info_map[sid].get('is_protected')) and 0 < (data['high'] - lp) <= (tick * 3):
                        if data['last_consumption'] >= 0.8 and not data['trig_策略預判']:
                            send_telegram_alert(sid, "策略預警：觀察蓄勢 (即將挑戰高點)", lp, "B")
                            data['trig_策略預判'] = True

                    # ✅ 策略四：N 字型態優先權
                    if data['state'] == 1 and lp >= data['point_a'] and data['point_b'] != 9999.0:
                        if not data['trig_策略四'] and is_量能二:
                            send_telegram_alert(sid, "策略四：N 字突破 (洗盤結束再發動)", lp, "A")
                            data['trig_策略四'] = True
                        data['point_a'] = lp; data['point_b'] = 9999.0; data['state'] = 0 
                    elif lp > data['point_a']:
                        data['point_a'] = lp; data['point_b'] = 9999.0; data['state'] = 1
                    elif data['state'] == 1 and lp < data['point_a']:
                        data['point_b'] = min(data['point_b'], lp)
                        if lp < (data['point_a'] + ref_p) / 2: data['state'] = 0

                    # 策略一與策略三
                    if is_突破一:
                        if is_量能二 and not data['trig_策略三']:
                            send_telegram_alert(sid, "策略三：價量齊揚 (強力多頭)", lp, "A")
                            data['trig_策略三'] = data['trig_策略一'] = True
                        elif not data['trig_策略一']:
                            send_telegram_alert(sid, "策略一：3K 突破", lp, "A")
                            data['trig_策略一'] = True

                except Exception as e:
                    print(f"console.log: [錯誤] {sid} 監控過程異常: {e}")
                
                time.sleep(Config.API_THROTTLE)
        else:
            time.sleep(60)

if __name__ == "__main__":
    main()