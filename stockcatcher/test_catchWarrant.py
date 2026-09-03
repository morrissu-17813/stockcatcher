import argparse
from datetime import datetime, time as datetime_time, timedelta, timezone
import json
import os
from pathlib import Path
import requests
import re
import time
import urllib3
from dotenv import load_dotenv

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}
SESSION = requests.Session()
VERIFY_SSL = True
MIN_DAYS_TO_EXPIRY = 30
MAX_OTM_PERCENT = 30
MIN_CALL_PUT_RATIO = 1.5
DEFAULT_MONITOR_INTERVAL = 300
DEFAULT_3K_SCAN_INTERVAL = 60
SNAPSHOT_FILE = Path(__file__).with_name("warrant_premarket_snapshot.json")
ENV_FILE = Path(__file__).with_name(".env")
CONCEPTS_FILE = Path(__file__).with_name("config") / "concepts.json"
KLINE_TIMEFRAME_MINUTES = 5
KLINE_VOLUME_MULTIPLIER = 1.2
OPENING_KLINE_VOLUME_MULTIPLIER = 1.8
KLINE_MIN_VOLUME_HISTORY = 5
WARRANT_VOLUME_GROWTH_PERCENT = 20
WARRANT_VOLUME_GROWTH_MINIMUM = 500
TAIPEI_TIMEZONE = timezone(timedelta(hours=8))
MARKET_OPEN = datetime_time(9, 0)
OPENING_NOISE_END = datetime_time(9, 15)
MARKET_CLOSE = datetime_time(13, 30)

load_dotenv(ENV_FILE)

def get_taipei_now():
    return datetime.now(TAIPEI_TIMEZONE)

def is_market_hours(now=None):
    now = now or get_taipei_now()
    return now.weekday() < 5 and MARKET_OPEN <= now.time() <= MARKET_CLOSE

def is_opening_noise_period(now=None):
    now = now or get_taipei_now()
    return now.weekday() < 5 and MARKET_OPEN <= now.time() < OPENING_NOISE_END

def load_concept_index():
    """建立股票代號到概念題材的反向索引。"""
    try:
        concepts = json.loads(CONCEPTS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        print(f"⚠️ 無法載入族群概念檔: {error}")
        return {}

    concept_index = {}
    for concept_name, stock_codes in concepts.items():
        for stock_code in stock_codes:
            concept_index.setdefault(str(stock_code), []).append(concept_name)
    return concept_index

def request_get(url, **kwargs):
    """發送 GET 並重試暫時性連線錯誤。"""
    global VERIFY_SSL

    last_error = None
    for attempt in range(3):
        try:
            response = SESSION.get(url, verify=VERIFY_SSL, **kwargs)
            response.raise_for_status()
            return response
        except requests.exceptions.SSLError as error:
            last_error = error
            if not VERIFY_SSL:
                break
            VERIFY_SSL = False
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            print("⚠️ SSL 憑證鏈驗證失敗，後續連線改以 verify=False 執行")
        except requests.exceptions.RequestException as error:
            last_error = error
            if attempt < 2:
                time.sleep(attempt + 1)

    raise last_error

def request_post(url, **kwargs):
    """發送 POST 並沿用 GET 的 SSL 降級與暫時性錯誤重試。"""
    global VERIFY_SSL

    last_error = None
    for attempt in range(3):
        try:
            response = SESSION.post(url, verify=VERIFY_SSL, **kwargs)
            response.raise_for_status()
            return response
        except requests.exceptions.SSLError as error:
            last_error = error
            if not VERIFY_SSL:
                break
            VERIFY_SSL = False
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            print("⚠️ SSL 憑證鏈驗證失敗，後續連線改以 verify=False 執行")
        except requests.exceptions.RequestException as error:
            last_error = error
            if attempt < 2:
                time.sleep(attempt + 1)

    raise last_error

# ---------------------------------------------------------
# 1. 抓取富邦權證成交量排行榜並映射至現股
# ---------------------------------------------------------
def fetch_fubon_volume_rank_stocks():
    """
    抓取認購／認售權證成交量榜，過濾品質後按現股彙總並計算認購認售比。
    """
    url = "https://warrants.fbs.com.tw/want/data/getWRankResult.aspx"
    headers = {**HEADERS, "Referer": "https://warrants.fbs.com.tw/want/wRank.aspx"}

    try:
        target_stocks = {}

        for callput in ("C", "P"):
            page = 1
            total_pages = 1

            while page <= total_pages:
                response = request_get(
                    url,
                    params={"rank": "sumvol_desc", "callput": callput, "page": page},
                    headers=headers,
                    timeout=20,
                )

                if page == 1:
                    page_match = re.search(r"totPage:'(\d+)'", response.text)
                    total_pages = int(page_match.group(1)) if page_match else 1

                for record in re.findall(r"\{([^{}]+)\}", response.text):
                    fields = {}
                    for field_name in (
                        "ulcode", "ulsname", "idx_cp", "days", "iom", "sumvol"
                    ):
                        field_match = re.search(
                            rf"\b{field_name}:\s*(?:'([^']*)'|([^,}}]+))",
                            record,
                        )
                        if field_match:
                            fields[field_name] = (
                                field_match.group(1)
                                if field_match.group(1) is not None
                                else field_match.group(2).strip()
                            )

                    stock_code = fields.get("ulcode", "")
                    if not re.fullmatch(r"\d{4}", stock_code):
                        continue

                    days = int(clean_num(fields.get("days")))
                    moneyness = clean_num(fields.get("iom"))
                    volume = int(clean_num(fields.get("sumvol")))
                    if days < MIN_DAYS_TO_EXPIRY or moneyness < -MAX_OTM_PERCENT:
                        continue

                    stock = target_stocks.setdefault(
                        stock_code,
                        {
                            "name": ''.join(fields.get("ulsname", "").split()),
                            "price": fields.get("idx_cp", "-"),
                            "call_volume": 0,
                            "put_volume": 0,
                        },
                    )
                    volume_key = "call_volume" if callput == "C" else "put_volume"
                    stock[volume_key] += volume

                page += 1

        for stock_code in list(target_stocks):
            stock = target_stocks[stock_code]
            call_volume = stock["call_volume"]
            put_volume = stock["put_volume"]
            stock["call_put_ratio"] = (
                call_volume / put_volume if put_volume > 0 else float("inf")
            )
            if call_volume == 0 or stock["call_put_ratio"] < MIN_CALL_PUT_RATIO:
                del target_stocks[stock_code]

        return target_stocks
    except Exception as e:
        print(f"❌ 抓取富邦權證網失敗: {e}")
        return {}

# ---------------------------------------------------------
# 2. 安全轉譯證交所/櫃買數字
# ---------------------------------------------------------
def clean_num(val):
    """清理 API 回傳的千分位逗號與異常字元"""
    if not val or val == '--':
        return 0.0
    val_str = str(val).replace(',', '').replace('+', '').strip()
    try:
        return float(val_str)
    except ValueError:
        return 0.0

# ---------------------------------------------------------
# 3. 抓取上市與上櫃三大法人買賣超數據 (TWSE + TPEx)
# ---------------------------------------------------------
def fetch_all_institutional_buyers():
    """
    抓取 TWSE (上市) 與 TPEx (上櫃) 三大法人買賣超，並篩選出符合籌碼條件的現股標的
    條件：自營商買賣超 > 0
    """
    valid_stocks = set()
    
    # --- Part A: 上市公司 (TWSE) ---
    twse_url = "https://www.twse.com.tw/rwd/zh/fund/T86?response=json"
    try:
        res = request_get(twse_url, headers=HEADERS, timeout=20).json()
        if res.get('stat') == 'OK' and 'data' in res:
            for row in res['data']:
                stock_code = row[0].strip()
                if not re.fullmatch(r'\d{4}', stock_code):
                    continue
                    
                dealer = clean_num(row[11])   # 自營商買賣超
                
                if dealer > 0:
                    valid_stocks.add(stock_code)
    except Exception as e:
        print(f"⚠️ 抓取 TWSE 三大法人失敗: {e}")
        
    time.sleep(1) # 避開 API 頻率限制
    
    # --- Part B: 上櫃公司 (TPEx) ---
    tpex_url = (
        "https://www.tpex.org.tw/web/stock/3insti/daily_trade/"
        "3itrade_hedge_result.php?l=zh-tw&o=json"
    )
    try:
        res = request_get(tpex_url, headers=HEADERS, timeout=20).json()
        tables = res.get('tables', [])
        if tables:
            for row in tables[0].get('data', []):
                stock_code = row[0].strip()
                if not re.fullmatch(r'\d{4}', stock_code):
                    continue
                    
                dealer = clean_num(row[22])   # 自營商合計買賣超
                
                if dealer > 0:
                    valid_stocks.add(stock_code)
    except Exception as e:
        print(f"⚠️ 抓取 TPEx 三大法人失敗: {e}")

    return valid_stocks

def build_monitoring_pool(warrant_stocks, institutional_stocks):
    """依盤前法人名單建立當下權證監控池。"""
    return {
        stock_code: warrant_stocks[stock_code]
        for stock_code in warrant_stocks
        if stock_code in institutional_stocks
    }

def save_premarket_snapshot(warrant_stocks, institutional_stocks, monitoring_pool):
    """將完整盤前基準寫入 JSON，供盤中與事後核對。"""
    def serialize_stocks(stocks):
        serialized = {}
        for stock_code, stock in stocks.items():
            serialized[stock_code] = dict(stock)
            if stock.get("call_put_ratio") == float("inf"):
                serialized[stock_code]["call_put_ratio"] = "Infinity"
        return serialized

    snapshot = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "conditions": {
            "min_days_to_expiry": MIN_DAYS_TO_EXPIRY,
            "max_otm_percent": MAX_OTM_PERCENT,
            "min_call_put_ratio": MIN_CALL_PUT_RATIO,
            "institutional_condition": "dealer_net_buy > 0",
        },
        "warrant_stocks": serialize_stocks(warrant_stocks),
        "institutional_stocks": sorted(institutional_stocks),
        "monitoring_pool": serialize_stocks(monitoring_pool),
    }
    SNAPSHOT_FILE.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )

def format_ratio(ratio):
    return "∞" if ratio == float("inf") else f"{ratio:.2f}"

def detect_effective_3k_breakout(bars, volume_multiplier=KLINE_VOLUME_MULTIPLIER):
    """判斷最後一根已收 K 是否突破前兩根高點並放量。"""
    if len(bars) < KLINE_MIN_VOLUME_HISTORY + 3:
        return None

    first_bar, second_bar, third_bar = bars[-3:]
    previous_bars = bars[:-3][-20:]
    breakout_price = max(first_bar["high"], second_bar["high"])
    previous_average_volume = sum(bar["volume"] for bar in previous_bars) / len(previous_bars)
    required_volume = max(
        first_bar["volume"],
        second_bar["volume"],
        previous_average_volume * volume_multiplier,
    )

    if third_bar["close"] <= breakout_price or third_bar["volume"] <= required_volume:
        return None

    return {
        "bar_time": third_bar["date"],
        "breakout_price": breakout_price,
        "close": third_bar["close"],
        "volume": third_bar["volume"],
        "required_volume": required_volume,
        "volume_ratio": third_bar["volume"] / previous_average_volume,
        "stop_price": min(first_bar["low"], second_bar["low"], third_bar["low"]),
    }

def fetch_effective_3k_breakout(stock_code, volume_multiplier=KLINE_VOLUME_MULTIPLIER):
    """取得已收盤 5 分 K，回傳最新有效 3K 突破訊號。"""
    api_key = os.getenv("FUGLE_API_KEY", "").strip()
    if not api_key:
        return None

    url = (
        "https://api.fugle.tw/marketdata/v1.0/stock/intraday/candles/"
        f"{stock_code}?timeframe={KLINE_TIMEFRAME_MINUTES}"
    )
    response = request_get(
        url,
        headers={"X-API-KEY": api_key},
        timeout=20,
    )
    bars = response.json().get("data", [])
    bars.sort(key=lambda bar: bar["date"])

    completed_bars = []
    for bar in bars:
        bar_time = datetime.fromisoformat(bar["date"])
        bar_end_time = bar_time.timestamp() + KLINE_TIMEFRAME_MINUTES * 60
        if bar_end_time <= time.time():
            completed_bars.append(bar)

    return detect_effective_3k_breakout(completed_bars, volume_multiplier)

def enrich_warrant_volume_growth(previous_pool, current_pool):
    """計算最近一次熱門榜更新的認購量增幅。"""
    for stock_code, stock in current_pool.items():
        previous_volume = previous_pool.get(stock_code, {}).get("call_volume", 0)
        volume_change = stock["call_volume"] - previous_volume
        growth_percent = (
            volume_change / previous_volume * 100 if previous_volume > 0 else 0.0
        )
        stock["warrant_volume_change"] = volume_change
        stock["warrant_volume_growth_percent"] = growth_percent
        stock["is_warrant_volume_accelerating"] = (
            previous_volume > 0
            and volume_change >= WARRANT_VOLUME_GROWTH_MINIMUM
            and growth_percent >= WARRANT_VOLUME_GROWTH_PERCENT
        )

def evaluate_concept_resonance(stock_code, current_pool, concept_index):
    """判斷同概念是否有另一檔熱門股同步出現認購量快速增加。"""
    stock_concepts = set(concept_index.get(stock_code, []))
    if not stock_concepts:
        return None

    peers = []
    matched_concepts = set()
    for peer_code, peer in current_pool.items():
        if peer_code == stock_code or not peer.get("is_warrant_volume_accelerating"):
            continue
        shared_concepts = stock_concepts.intersection(concept_index.get(peer_code, []))
        if shared_concepts:
            peers.append(f"{peer_code} {peer['name']}")
            matched_concepts.update(shared_concepts)

    if not peers:
        return None
    return {"concepts": sorted(matched_concepts), "peers": peers[:4]}

def evaluate_signal_grade(stock_code, stock, current_pool, concept_index):
    """A=有效3K；AA=加上權證量增；AAA=再加上族群共振。"""
    accelerating = stock.get("is_warrant_volume_accelerating", False)
    resonance = evaluate_concept_resonance(stock_code, current_pool, concept_index)
    if accelerating and resonance:
        return "AAA", resonance
    if accelerating:
        return "AA", None
    return "A", None

def send_telegram_3k_alert(stock_code, stock, signal, category, grade, resonance):
    """發送有效 3K 突破通知；Telegram 設定僅從環境變數取得。"""
    token = os.getenv("TELEGRAM_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        print("⚠️ 未設定 TELEGRAM_TOKEN 或 TELEGRAM_CHAT_ID，略過通知")
        return False

    grade_badges = {"A": "🎯 A", "AA": "🔥 AA", "AAA": "🚀 AAA"}
    message_lines = [
        "🚨 [訊號觸發]",
        f"🎯 *核心策略：* 🎫 [權證主力標的] 有效3K突破 {grade_badges[grade]}",
        "━━━━━━━━━━━━",
        f"📈 *標的：* [{stock_code} {stock['name']}](https://www.nstock.tw/stock_info?stock_id={stock_code})",
        f"🏷️ *分類：* `{category}`",
        f"💰 *現價：* `{stock['price']}`",
        f"📐 *K3收盤／突破價：* `{signal['close']}` / `{signal['breakout_price']}`",
        f"📊 *K3量能：* `{signal['volume']:,}`（均量 `{signal['volume_ratio']:.2f}x`）",
        f"🎫 *認購量增：* `{stock.get('warrant_volume_change', 0):+,}` "
        f"(`{stock.get('warrant_volume_growth_percent', 0.0):+.1f}%`)",
        f"🛡️ *策略停損：* `{signal['stop_price']}`",
    ]
    if resonance:
        message_lines.extend(
            [
                "🌊 *TIDE 族群共振：*",
                f"　題材：`{'、'.join(resonance['concepts'][:2])}`",
                f"　同步發動：`{'、'.join(resonance['peers'])}`",
                "　MA20：`待日線資料補強，不列入本次評級`",
            ]
        )
    message_lines.extend(
        [
            "━━━━━━━━━━━━",
            f"⏰ {get_taipei_now():%Y-%m-%d %H:%M:%S}",
        ]
    )
    response = request_post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={
            "chat_id": chat_id,
            "text": "\n".join(message_lines),
            "parse_mode": "Markdown",
        },
        timeout=20,
    )
    return response.ok

def scan_effective_3k_breakouts(current_pool, core_pool, sent_signals, concept_index):
    """掃描盤中熱門池，只通知尚未發送的有效 3K 訊號。"""
    signal_count = 0
    volume_multiplier = (
        OPENING_KLINE_VOLUME_MULTIPLIER
        if is_opening_noise_period()
        else KLINE_VOLUME_MULTIPLIER
    )
    for stock_code, stock in current_pool.items():
        try:
            signal = fetch_effective_3k_breakout(stock_code, volume_multiplier)
            if not signal:
                continue

            signal_key = f"{stock_code}:{signal['bar_time']}"
            if signal_key in sent_signals:
                continue

            category = "盤前核心池" if stock_code in core_pool else "盤中熱門池"
            grade, resonance = evaluate_signal_grade(
                stock_code, stock, current_pool, concept_index
            )
            print(
                f"🚨 有效3K突破 [{grade}｜{category}]: {stock_code} {stock['name']} "
                f"收盤 {signal['close']} > {signal['breakout_price']}，"
                f"量能 {signal['volume_ratio']:.2f}x"
            )
            if send_telegram_3k_alert(
                stock_code, stock, signal, category, grade, resonance
            ):
                sent_signals.add(signal_key)
            signal_count += 1
        except Exception as error:
            print(f"⚠️ {stock_code} 3K 掃描失敗: {error}")
        time.sleep(0.2)

    if signal_count == 0:
        print("本輪沒有新的有效 3K 突破訊號")

def print_pool(title, pool):
    print(f"\n========== {title} ({len(pool)} 檔) ==========")
    print("排名  股票代號  股票名稱      現股價格    認購量彙總    認售量彙總  認購認售比")
    ranked_pool = sorted(
        pool.items(),
        key=lambda item: item[1]["call_volume"],
        reverse=True,
    )
    for index, (stock_code, stock) in enumerate(ranked_pool, start=1):
        print(
            f"{index:>2}.   {stock_code:<8}"
            f"{stock['name']:<10}"
            f"{stock['price']:>10}"
            f"{stock['call_volume']:>14,}"
            f"{stock['put_volume']:>14,}"
            f"{format_ratio(stock['call_put_ratio']):>12}"
        )
    if not pool:
        print("本次沒有符合條件的現股")
    print("==================================")

def print_incremental_changes(baseline_pool, core_pool, previous_pool, current_pool):
    """輸出相對盤前與上一輪的新增、移除及量價變化。"""
    baseline_codes = set(baseline_pool)
    core_codes = set(core_pool)
    previous_codes = set(previous_pool)
    current_codes = set(current_pool)
    new_codes = current_codes - baseline_codes
    entered_codes = current_codes - previous_codes
    removed_codes = previous_codes - current_codes
    active_core_codes = current_codes & core_codes
    intraday_watch_codes = current_codes - core_codes

    print(f"\n[{datetime.now():%Y-%m-%d %H:%M:%S}] 盤中增量監控")
    print(
        f"目前熱門 {len(current_codes)} 檔｜核心池熱門 {len(active_core_codes)} 檔｜"
        f"盤中觀察 {len(intraday_watch_codes)} 檔"
    )
    print(
        f"盤前後新進 {len(new_codes)} 檔｜"
        f"本輪新進 {len(entered_codes)} 檔｜本輪移除 {len(removed_codes)} 檔"
    )

    for label, codes in (("盤前後新進", new_codes), ("本輪新進", entered_codes)):
        for stock_code in sorted(codes):
            stock = current_pool[stock_code]
            category = "核心池熱門" if stock_code in core_codes else "盤中新熱門"
            print(
                f"{label} [{category}]: {stock_code} {stock['name']} "
                f"價格 {stock['price']} 認購量 {stock['call_volume']:,} "
                f"認購認售比 {format_ratio(stock['call_put_ratio'])}"
            )

    for stock_code in sorted(removed_codes):
        stock = previous_pool[stock_code]
        print(f"本輪移除: {stock_code} {stock['name']}")

    for stock_code in sorted(current_codes & previous_codes):
        current = current_pool[stock_code]
        previous = previous_pool[stock_code]
        volume_change = current["call_volume"] - previous["call_volume"]
        current_price = clean_num(current["price"])
        previous_price = clean_num(previous["price"])
        price_change = current_price - previous_price
        if volume_change != 0 or price_change != 0:
            category = "核心池熱門" if stock_code in core_codes else "盤中觀察"
            print(
                f"更新 [{category}]: {stock_code} {current['name']} "
                f"認購量 {volume_change:+,}｜價格 {price_change:+.2f} "
                f"(目前 {current['price']})"
            )

def run_intraday_monitor(warrant_interval_seconds, scan_interval_seconds):
    """建立盤前基準後，以獨立週期更新熱門榜與掃描 3K。"""
    print("建立盤前基準資料...")
    baseline_warrants = fetch_fubon_volume_rank_stocks()
    institutional_stocks = fetch_all_institutional_buyers()
    baseline_pool = build_monitoring_pool(baseline_warrants, institutional_stocks)
    enrich_warrant_volume_growth({}, baseline_warrants)
    save_premarket_snapshot(baseline_warrants, institutional_stocks, baseline_pool)
    print_pool("盤前權證熱門池", baseline_warrants)
    print_pool("盤前法人核心池", baseline_pool)
    print(f"盤前快照已儲存：{SNAPSHOT_FILE}")
    print("盤中熱門池不套用法人條件，法人名單僅用於標示盤前核心標的。")
    print(
        f"有效3K：{KLINE_TIMEFRAME_MINUTES}分K收盤突破前2根高點，"
        f"且K3量大於前2根及前序均量 {KLINE_VOLUME_MULTIPLIER} 倍。"
    )
    print(
        f"熱門榜每 {warrant_interval_seconds} 秒更新；"
        f"3K 每 {scan_interval_seconds} 秒掃描；按 Ctrl+C 結束。"
    )

    concept_index = load_concept_index()
    current_warrants = baseline_warrants
    sent_3k_signals = set()
    last_warrant_refresh = time.monotonic()
    last_3k_scan = 0.0
    outside_market_logged = False
    try:
        while True:
            now = get_taipei_now()
            if now.weekday() < 5 and now.time() > MARKET_CLOSE:
                print(f"[{now:%H:%M:%S}] 已收盤，盤中監控自動停止。")
                break

            if not is_market_hours(now):
                if not outside_market_logged:
                    print(
                        f"[{now:%Y-%m-%d %H:%M:%S}] 非交易時段，"
                        "暫停熱門榜與 3K 掃描。"
                    )
                    outside_market_logged = True
                time.sleep(min(scan_interval_seconds, 60))
                continue

            outside_market_logged = False
            monotonic_now = time.monotonic()

            if monotonic_now - last_warrant_refresh >= warrant_interval_seconds:
                refreshed_warrants = fetch_fubon_volume_rank_stocks()
                if refreshed_warrants:
                    enrich_warrant_volume_growth(current_warrants, refreshed_warrants)
                    print_incremental_changes(
                        baseline_warrants,
                        baseline_pool,
                        current_warrants,
                        refreshed_warrants,
                    )
                    current_warrants = refreshed_warrants
                else:
                    print("⚠️ 本輪權證資料為空，保留上一輪資料")
                last_warrant_refresh = monotonic_now

            if monotonic_now - last_3k_scan >= scan_interval_seconds:
                if is_opening_noise_period(now):
                    print(
                        f"[{now:%H:%M:%S}] 開盤高雜訊時段，"
                        f"3K 量能門檻提高至 {OPENING_KLINE_VOLUME_MULTIPLIER}x"
                    )
                scan_effective_3k_breakouts(
                    current_warrants,
                    baseline_pool,
                    sent_3k_signals,
                    concept_index,
                )
                last_3k_scan = monotonic_now

            time.sleep(1)
    except KeyboardInterrupt:
        print("\n盤中監控已停止。")

# ---------------------------------------------------------
# 4. 整合主程式：生成盤中精準監控股池
# ---------------------------------------------------------
def generate_monitoring_pool():
    print("🔍 正在彙總富邦認購／認售權證成交量排行榜...")
    warrant_stocks = fetch_fubon_volume_rank_stocks()
    print(f"👉 通過權證品質與認購認售比條件: {len(warrant_stocks)} 檔")
    
    print("🔍 正在抓取上市/上櫃法人籌碼【自營商買超】...")
    institutional_stocks = fetch_all_institutional_buyers()
    print(f"👉 符合法人籌碼條件現股數量 (上市+上櫃): {len(institutional_stocks)} 檔")
    
    pool = build_monitoring_pool(warrant_stocks, institutional_stocks)
    final_pool = sorted(pool, key=lambda code: pool[code]["call_volume"], reverse=True)
    print("\n========== 交集篩選結果 ==========")
    print(
        f"富邦權證條件標的 {len(warrant_stocks)} 檔 "
        f"∩ 法人條件標的 {len(institutional_stocks)} 檔 "
        f"= 最終監控池 {len(final_pool)} 檔"
    )
    print(
        f"條件：到期 >= {MIN_DAYS_TO_EXPIRY} 天、價外 <= {MAX_OTM_PERCENT}%、"
        f"榜內認購認售比 >= {MIN_CALL_PUT_RATIO}、自營商買超"
    )
    print("排名  股票代號  股票名稱      現股價格    認購量彙總    認售量彙總  認購認售比")

    for index, stock_code in enumerate(final_pool, start=1):
        stock = warrant_stocks[stock_code]
        ratio = stock["call_put_ratio"]
        ratio_text = "∞" if ratio == float("inf") else f"{ratio:.2f}"
        print(
            f"{index:>2}.   {stock_code:<8}"
            f"{stock['name']:<10}"
            f"{stock['price']:>10}"
            f"{stock['call_volume']:>14,}"
            f"{stock['put_volume']:>14,}"
            f"{ratio_text:>12}"
        )

    if not final_pool:
        print("本次沒有同時符合條件的現股")
    print("==================================")
    
    return final_pool

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="權證熱門標的監控池")
    parser.add_argument("--monitor", action="store_true", help="啟動盤中增量監控")
    parser.add_argument(
        "--interval",
        type=int,
        default=DEFAULT_MONITOR_INTERVAL,
        help="權證熱門榜更新秒數，預設 300 秒",
    )
    parser.add_argument(
        "--scan-interval",
        type=int,
        default=DEFAULT_3K_SCAN_INTERVAL,
        help="3K 掃描秒數，預設 60 秒",
    )
    args = parser.parse_args()

    if args.monitor:
        run_intraday_monitor(
            max(args.interval, 60),
            max(args.scan_interval, 30),
        )
    else:
        monitoring_pool = generate_monitoring_pool()

