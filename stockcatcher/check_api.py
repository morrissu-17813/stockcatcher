import os
import time
import requests
import json
import urllib3
from datetime import datetime, timedelta, timezone, time as dtime
from typing import Dict, List, Any, Optional

# 🤫 隱藏 SSL 警告，保持生產環境日誌整潔
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ============================================================
# ⚙️ [系統配置區]
# ============================================================
class Config:
    # 🔐 憑證管理：使用環境變數或預留位置，禁止硬編碼 API Key
    FINMIND_TOKEN = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJ1c2VyX2lkIjoiRVNCMTc4MTMiLCJlbWFpbCI6Im0yOTk0MDUwOUBob3RtYWlsLmNvbSJ9.iGsA_PLkanve2aATgXU-RD2i7RKOHSLzMEmASMBOcDE" 
    FUGLE_API_KEY ="MzJiNjhmNjAtMzRjMy00OGZiLTg3YWQtMTJmMjg3NGE0MDNjIGJlNGVmY2Q2LTE5NDQtNDUzZi1iNTcxLTI5NmIzM2QwOTIzZQ=="
    TELEGRAM_TOKEN = "8480482512:AAGin83kwa61oa5F5rBj4NQMow-C9jsbJug"
    TELEGRAM_CHAT_ID = "-1003613268841"



    # 📈 策略監控參數
    # --- 選股池配額設定 ---
    TSE_QUOTA = 90  # 上市增加至 90 檔
    OTC_QUOTA = 40   # 上櫃增加至 40 檔
    VOL_EST_THRESHOLD = 1.6          # 預估量比門檻 (1.6x)
    STOP_LOSS_RATIO = 0.95           # 預設停損比率 (現價 -5%)
    POOL_REFRESH_INTERVAL = 1200     # 股池更新頻率 (每 20 分鐘刷新熱門榜)
    MAX_MONITOR_LIMIT = 100          # 同時監控上限 (上市+上櫃)
    API_THROTTLE_SLEEP = 1.2         # 節流時間 (避免觸發 API Rate Limit)

    # ⏰ 時間控制邏輯
    RECORD_END_TIME = dtime(9, 15)   # 3K 區間紀錄截止 (09:00-09:15)
    START_MONITOR_TIME = dtime(9, 16)# 策略突破觸發起始時間 (09:16起)

    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

# 🏆 強化題材映射字典：結合名稱、產業、概念標籤
THEME_KEYWORDS = {
    "AI伺服器/零組件": ["廣達", "緯創", "技嘉", "英業達", "緯穎", "鴻海", "電腦及週邊設備業", "營邦", "勤誠", "南俊"],
    "半導體/IC設計": ["台積電", "聯發科", "世芯", "創意", "智原", "半導體業", "昇陽半導體", "聯電", "旺宏", "2344"],
    "CoWoS/先進封裝": ["弘塑", "辛耘", "萬潤", "均華", "志聖", "其他電子業"],
    "液冷/散熱模組": ["雙鴻", "奇鋐", "建準", "尼得科超眾", "晟銘電", "電子零組件業", "高力"],
    "矽光子/CPO": ["波若威", "上詮", "聯鈞", "光聖", "通信網路業", "華星光"],
    "低軌衛星/航太": ["華通", "昇達科", "啟碁", "耀華", "金像電", "元太", "邑錡", "全新", "2455", "2313"]
}

# 全域狀態記憶體
global_stock_info: Dict[str, Dict] = {} # 代號 -> {名稱, 產業, 市場, 題材清單}
stock_info_map: Dict[str, Any] = {}     # 監控池資訊
monitor_data: Dict[str, Any] = {}       # 監控池價量數據

# ------------------------------------------------------------
# 🛠️ 基礎工具函式 (Utils)
# ------------------------------------------------------------

def get_now_tw() -> datetime:
    """ 獲取台北標準時間 (UTC+8) """
    return datetime.now(timezone.utc) + timedelta(hours=8)

def get_passed_minutes() -> float:
    """ 計算開盤至今經過的分鐘數 (09:00 起算) """
    now = get_now_tw()
    start = now.replace(hour=9, minute=0, second=0, microsecond=0)
    passed = (now - start).total_seconds() / 60
    return max(1, min(270, passed))

def init_global_mapping():
    """ 
    建立全市場名冊映射與題材庫
    解決「上櫃資料缺失」與「題材不完整」的核心機制
    """
    print("📡 正在同步全市場基本資料與概念題材 (FinMind)...", flush=True)
    url = "https://api.finmindtrade.com/api/v4/data"
    try:
        # 1. 抓取名冊 (包含名稱與官方產業分類)
        res_info = requests.get(url, params={"dataset": "TaiwanStockInfo", "token": Config.FINMIND_TOKEN}, timeout=15).json()
        for item in res_info.get('data', []):
            industry = item['industry_category']
            global_stock_info[item['stock_id']] = {
                'name': item['stock_name'],
                'industry': industry,
                'market': '上市' if industry == '上市' else '上櫃',
                'concept': []
            }
        # 2. 抓取概念股資料集，強化市場題材識別度
        res_concept = requests.get(url, params={"dataset": "TaiwanStockConcept", "token": Config.FINMIND_TOKEN}, timeout=15).json()
        for item in res_concept.get('data', []):
            sid = item.get('stock_id')
            if sid in global_stock_info:
                global_stock_info[sid]['concept'].append(item.get('stock_concept', ''))
        print(f"✅ 名冊同步完成，共計 {len(global_stock_info)} 檔標的。", flush=True)
    except Exception as e:
        print(f"❌ 名冊同步失敗: {e}", flush=True)

def get_refined_theme(code: str) -> str:
    """ 多維度模糊比對題材，優先匹配熱點關鍵字 """
    info = global_stock_info.get(code, {})
    name, industry = info.get('name', ''), info.get('industry', '')
    concepts_list = info.get('concept', [])
    concepts_str = "".join(concepts_list)
    search_str = f"{code}{name}{industry}{concepts_str}"
    
    # 1. 優先權比對：自定義熱點關鍵字
    for theme, keywords in THEME_KEYWORDS.items():
        if any(kw in search_str for kw in keywords): return theme
        
    # 2. 次要權比對：顯示抓取到的第一個核心概念
    if concepts_list: return concepts_list[0]
    
    return "熱門成交追蹤"

# ------------------------------------------------------------
# 📡 數據通訊與警報 (Alerts)
# ------------------------------------------------------------

def send_tg_alert(stock_id: str, strategy: str, price: float, high: float, low: float, est_ratio: float, theme: str = "追蹤中"):
    """ 發送 Telegram 通知，包含停損點計算與即時圖表連結 """
    code = stock_id.split(' ')[0]
    chart_url = f"https://www.fugle.tw/ai/{code}"
    # 計算停損價位：觸發價之 -5%
    stop_loss = round(price * Config.STOP_LOSS_RATIO, 2)
    
    header = "🔥【價量齊揚】" if "+" in strategy else "🚀【價格突破】" if "3K" in strategy else "📊【量能激增】"
    if "🧪" in strategy: header = "🧪【啟動測試】"

    msg = (
        f"{header}：{strategy}\n"
        f"━━━━━━━━━━━━━━\n"
        f"📈 *標的：* {stock_id}\n"
        f"💰 *現價：* `{price}` | 🛑 *停損：* `{stop_loss}`\n"
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
    except Exception as e:
        print(f"⚠️ Telegram 發送失敗: {e}", flush=True)

# ------------------------------------------------------------
# 🏛️ 市場同步模組 (100:50 精準配額優化版)
# ------------------------------------------------------------
def sync_market_pool():
    """ 
    [架構說明]：
    1. 實作 100:50 配額制：總計監控全市場 150 檔最活躍標的。
    2. 資料源：直接對接 TWSE 與 TPEx 官方 OpenAPI，排除第三方延遲與權限問題。
    """
    tw_now = get_now_tw()
    print(f"\n" + "="*60)
    print(f"🛰️ [{tw_now.strftime('%H:%M:%S')}] 啟動動態掃描 (配額：上市 {Config.TSE_QUOTA} / 上櫃 {Config.OTC_QUOTA})")
    print("="*60, flush=True)
    
    tse_pool = []
    otc_pool = []
    
    # --- Part 1: 上市排行同步 (TWSE) ---
    try:
        tse_url = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
        tse_res = requests.get(tse_url, timeout=15, verify=False)
        if tse_res.status_code == 200:
            for i in tse_res.json():
                code = i.get('Code', '')
                if len(code) == 4:
                    # 處理字串格式成交量並轉換為張數
                    vol_str = str(i.get('TradeVolume', '0')).replace(',', '')
                    vol = int(vol_str) // 1000
                    tse_pool.append({'code': code, 'vol': vol, 'm': '上市'})
    except Exception as e:
        print(f"⚠️ TWSE 連線異常: {e}")

    # --- Part 2: 上櫃排行同步 (TPEx) ---
    try:
        otc_url = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_quotes"
        otc_res = requests.get(otc_url, timeout=15, verify=False)
        if otc_res.status_code == 200:
            for item in otc_res.json():
                code = str(item.get('SecuritiesCompanyCode', '')).strip()
                if len(code) == 4:
                    # TPEx 格式相容性處理 (Float/Comma)
                    vol_raw = str(item.get('TradingVolume', '0')).replace(',', '')
                    vol = int(float(vol_raw)) // 1000
                    otc_pool.append({'code': code, 'vol': vol, 'm': '上櫃'})
            print(f"📊 TPEx 官方數據同步成功 (共 {len(otc_pool)} 筆)")
    except Exception as e:
        print(f"❌ TPEx 連線異常: {e}")

    # --- Part 3: 執行配額排序與資料結構初始化 ---
    # 分別按成交量 (vol) 進行降冪排序，確保選出最熱門標的
    top_tse = sorted(tse_pool, key=lambda x: x['vol'], reverse=True)[:Config.TSE_QUOTA]
    top_otc = sorted(otc_pool, key=lambda x: x['vol'], reverse=True)[:Config.OTC_QUOTA]
    
    final_list = top_tse + top_otc
    
    # 測試標的 9999 永遠置入，方便驗證系統通知
    test_stocks = [{'code': '9999', 'm': '測試', 'vol': 1000}]

    for item in (test_stocks + final_list):
        code = item['code']
        # 從全域映射資料 (init_global_mapping) 獲取靜態資訊
        info = global_stock_info.get(code, {'name': '偵測中', 'industry': '未知'})
        
        # 僅針對尚未在池子中的標的進行初始化，避免覆蓋掉盤中已記錄的 High/Low
        if code not in stock_info_map:
            theme = get_refined_theme(code) # 題材辨識
            
            stock_info_map[code] = {
                'name': info['name'], 
                'market': item['m'], 
                'theme': theme
            }
            # 初始化監控狀態機，y_vol 將作為盤中 1.6 倍預估量的分母
            monitor_data[code] = {
                "high": 110.0 if "999" in code else 0.0, 
                "low": 95.0 if "999" in code else 9999.0, 
                "y_vol": item['vol'] if item['vol'] > 0 else 1000, 
                "trig_p": False, # 價格觸發標記
                "trig_v": False, # 量能觸發標記
                "trig_c": False  # 複合觸發標記 (價+量)
            }
    
    # --- 輸出同步統計摘要 ---
    tse_actual = len([x for x in stock_info_map.values() if x['market'] == '上市'])
    otc_actual = len([x for x in stock_info_map.values() if x['market'] == '上櫃'])
    
    print("-" * 60)
    print(f"✅ 同步完成！目前全域池子：{len(stock_info_map)} 檔")
    print(f"   - 上市 (TSE) 成功入庫: {tse_actual} / 100")
    print(f"   - 上櫃 (OTC) 成功入庫: {otc_actual} / 50")
    print("="*60, flush=True)
# ------------------------------------------------------------
# 🏁 主程序入口 (Main Loop)
# ------------------------------------------------------------

def main():
    print("="*80, flush=True)
    print(f"🛡️ 偵察機啟動 | 蘇蘇的天機選股系統 | {get_now_tw().strftime('%Y-%m-%d %H:%M:%S')}", flush=True)
    print("="*80, flush=True)

    init_global_mapping()  
    sync_market_pool()     

    # 💡 重要修復：在進入迴圈前初始化時間變數
    last_sync_time = time.time()  # 初始化同步時間

    # 💡 啟動測試通知：僅在此發送一次，確保題材顯示正常
    test_theme = get_refined_theme("9999")
    send_tg_alert("9999 系統測試標的", "🧪 偵察機啟動完成通訊測試", 125.0, 110.0, 95.0, 3.0, test_theme)
    
    while True:
        tw_now = get_now_tw()
        now_time = tw_now.time()
        passed_min = get_passed_minutes()

        if time.time() - last_sync_time > Config.POOL_REFRESH_INTERVAL:
            sync_market_pool()
            last_sync_time = time.time()

        print(f"\n[掃描輪次: {tw_now.strftime('%H:%M:%S')}]", flush=True)
        print(f"{'代號名稱':<12} | {'市場':<4} | {'現價':<6} | {'量比':<5} | {'3K高':<6} | {'題材'}", flush=True)
        print("-" * 85, flush=True)

        for symbol in list(stock_info_map.keys()):
            info, data = stock_info_map[symbol], monitor_data[symbol]
            try:
                if "999" in symbol:
                    quote = {"p": 125.0 if symbol=="9999" else 105.0, "v": 3000}
                else:
                    f_url = f"https://api.fugle.tw/marketdata/v1.0/stock/intraday/quote/{symbol}"
                    res = requests.get(f_url, headers={"X-API-KEY": Config.FUGLE_API_KEY.strip()}, timeout=5)
                    quote = {"p": res.json().get('lastPrice'), "v": res.json().get('total', {}).get('tradeVolume', 0)//1000} if res.status_code==200 else None
                
                if not quote or not quote['p']: continue
                lp, v = quote['p'], quote['v']
                est_ratio = round((v * (270 / passed_min)) / data['y_vol'], 2) if data['y_vol'] > 0 else 0
                
                # --- 🔥 3K 紀錄邏輯 ---
                if now_time < Config.RECORD_END_TIME and "999" not in symbol:
                    if lp > data["high"]: data["high"] = lp
                    if lp < data["low"] or data["low"] == 9999.0: data["low"] = lp

                # --- 🚀 突破判定 ---
                is_p_break = (lp > data['high'] > 0) and (now_time >= Config.START_MONITOR_TIME or "999" in symbol)
                is_v_surge = (est_ratio >= Config.VOL_EST_THRESHOLD)
                
                strat = ""
                if is_p_break and is_v_surge and not data["trig_c"]: strat = "價量齊揚"; data["trig_c"] = True
                elif is_p_break and not data["trig_p"] and not data["trig_c"]: strat = "3K突破"; data["trig_p"] = True
                elif is_v_surge and not data["trig_v"] and not data["trig_c"]: strat = "量能激增"; data["trig_v"] = True

                display_name = f"{symbol} {info['name']}"
                print(f"{display_name:<12} | {info['market']:<4} | {lp:<8} | {est_ratio:<6} | {data['high']:<8} | {info['theme']}", flush=True)

                if strat:
                    send_tg_alert(display_name, strat, lp, data['high'], data['low'], est_ratio, info['theme'])

            except Exception: pass
            time.sleep(Config.API_THROTTLE_SLEEP)
        time.sleep(5)

if __name__ == "__main__":
    main()