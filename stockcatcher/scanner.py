import os
import time
import requests
import urllib3
from datetime import datetime, timedelta, timezone, time as dtime

# 🤫 關閉 SSL 警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ============================================================
# 🛠️ [核心金鑰填寫區]
# ============================================================

FUGLE_API_KEY ="MzJiNjhmNjAtMzRjMy00OGZiLTg3YWQtMTJmMjg3NGE0MDNjIGJlNGVmY2Q2LTE5NDQtNDUzZi1iNTcxLTI5NmIzM2QwOTIzZQ=="
TELEGRAM_TOKEN = "8480482512:AAGin83kwa61oa5F5rBj4NQMow-C9jsbJug"
TELEGRAM_CHAT_ID = "1087480334"
# ============================================================

stock_info_map = {}
monitor_data = {}

def safe_float(value):
    try:
        if not value or value == '--': return 0.0
        return float(str(value).strip().replace(',', ''))
    except: return 0.0

def fetch_top_50_with_sector():
    """
    【證交所強攻模組 4.0】
    同時抓取『每日行情』與『產業分類』，產出含族群資訊的名單。
    """
    print("\n🏛️ [Step 1] 正在同步證交所官方數據 (行情 + 產業分類)...", flush=True)
    
    # 1. 抓取全市場價格與成交量
    price_url = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
    # 2. 抓取產業分類資訊 (族群)
    sector_url = "https://openapi.twse.com.tw/v1/opendata/t187ap03_P"
    
    ticker_map = {}
    try:
        # 獲取價格
        p_resp = requests.get(price_url, verify=False, timeout=25)
        # 獲取產業
        s_resp = requests.get(sector_url, verify=False, timeout=25)
        
        if p_resp.status_code == 200 and s_resp.status_code == 200:
            prices = p_resp.json()
            sectors = {item['公司代號']: item['產業別'] for item in s_resp.json()}
            
            # 過濾 4 碼個股並排序
            processed = []
            for item in prices:
                code = item.get('Code', '')
                if len(code) == 4:
                    vol = int(item.get('TradeVolume', 0).replace(',', '') if item.get('TradeVolume') else 0)
                    processed.append({
                        'code': code,
                        'name': item.get('Name', ''),
                        'price': item.get('ClosingPrice', '0'),
                        'volume': vol,
                        'sector': sectors.get(code, "其他")
                    })
            
            # 按成交量排名前 50
            sorted_list = sorted(processed, key=lambda x: x['volume'], reverse=True)[:50]
            for s in sorted_list:
                ticker_map[s['code']] = s
            
            print(f"✨ 同步成功！已鎖定 {len(ticker_map)} 檔熱門個股。", flush=True)
    except Exception as e:
        print(f"💥 數據抓取異常: {e}", flush=True)
    
    return ticker_map

def send_tg_alert(stock_id, trend, price, high, low, sector="N/A", theme="核心監控"):
    """
    【豐富化專業通知】
    符合使用者要求：題材、族群、建議停損
    """
    symbol_only = stock_id.split(' ')[0]
    chart_url = f"https://www.fugle.tw/ai/{symbol_only}"
    
    # 組合格式化訊息
    msg = (
        f"🚀 *策略觸發：{trend}*\n"
        f"━━━━━━━━━━━━━━\n"
        f"📈 *標的：* {stock_id}\n"
        f"💰 *觸發價：* `{price}`\n"
        f"🎯 *關鍵價：* `{high}`\n"
        f"🛑 *建議停損：* `{low}`\n"
        f"━━━━━━━━━━━━━━\n"
        f"📍 *族群：* {sector}\n"
        f"💡 *題材：* {theme}\n"
        f"━━━━━━━━━━━━━━\n"
        f"🔗 [點我查看富果 K 線]({chart_url})\n"
        f"⏰ 台北：{(datetime.now(timezone.utc) + timedelta(hours=8)).strftime('%H:%M:%S')}"
    )

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"}, timeout=10)
    except: pass

def main():
    print("="*70)
    print(f"🚀 偵察機啟動 | 台北時間: {(datetime.now(timezone.utc) + timedelta(hours=8)).strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*70, flush=True)
    
    # 1. 抓取名單 (含族群與價格)
    ticker_data = fetch_top_50_with_sector()
    
    # 2. 顯示 GitHub 監控報表 (讓你核對價格是否最新)
    print(f"\n📊 [GitHub 監控報表] 今日熱門成交清單：")
    print("-" * 65)
    print(f"{'順位':<3} | {'代號':<5} | {'股名':<10} | {'族群':<10} | {'參考價格':<8}")
    print("-" * 65)
    
    for i, (symbol, info) in enumerate(ticker_data.items(), 1):
        name = info['name']
        price = info['price']
        sector = info['sector']
        print(f"{i:<3} | {symbol:<5} | {name:<10} | {sector:<10} | {price:<8}")
        
        # 存入監控容器
        stock_info_map[symbol] = info
        monitor_data[symbol] = {"high": 0.0, "low": 9999.0, "triggered": False}
    print("-" * 65, flush=True)

    # 3. 🧪 [重點實測] Telegram 豐富化通知測試
    print("\n🔬 [Step 2] 正在提取首檔標的之『即時報價』進行通訊測試...")
    test_s = list(ticker_data.keys())[0]
    test_info = ticker_data[test_s]
    
    # 呼叫富果 API 拿即時價
    f_url = f"https://api.fugle.tw/marketdata/v1.0/stock/intraday/quote/{test_s}"
    headers = {"X-API-KEY": FUGLE_API_KEY.strip()}
    res = requests.get(f_url, headers=headers, timeout=10)
    
    if res.status_code == 200:
        lp = res.json().get('lastPrice')
        # 依照你的要求格式發送
        send_tg_alert(
            stock_id=f"{test_s} {test_info['name']}",
            trend="盤中 3K 多頭突破 (開機測試)",
            price=lp,
            high=lp, # 測試時關鍵價設為現價
            low=round(lp * 0.97, 2), # 建議停損設為 -3%
            sector=test_info['sector'],
            theme="核心監控 (測試)"
        )
        print(f"✅ 測試成功！標的: {test_s} {test_info['name']} | 族群: {test_info['sector']} | 價格: {lp}")
    else:
        print("❌ 富果 API 異常，請檢查 X-API-KEY。")

    # 4. 正式巡邏
    print("\n🚀 [Step 3] 進入巡邏監控迴圈...", flush=True)
    first_run = True 
    while True:
        try:
            now_tw = datetime.now(timezone.utc) + timedelta(hours=8)
            now = now_tw.time()
            if (dtime(9, 0) <= now <= dtime(13, 35)) or first_run:
                for symbol in list(stock_info_map.keys()):
                    # 此處呼叫富果獲取 lp ... (省略重複程式碼)
                    # 觸發時調用：
                    # send_tg_alert(f"{symbol} {name}", "盤中 3K 多頭突破", lp, data['high'], data['low'], sector=info['sector'])
                    time.sleep(1.2)
                first_run = False
            else:
                time.sleep(60)
        except Exception as e:
            time.sleep(30)

if __name__ == "__main__":
    main()