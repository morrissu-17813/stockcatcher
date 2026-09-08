from typing import Dict, Any, Optional, List
from supabase import Client

# ==========================================
# 🔍 0. 共用輔助層：真實股名查詢
# ==========================================
def get_real_stock_names(supabase: Client, symbols: list) -> dict:
    """從資料庫中批次查詢真實的股票名稱"""
    if not symbols:
        return {}
    
    unique_symbols = list(set(symbols))
    real_names = {}
    
    try:
        response = supabase.table("theme_stocks") \
            .select("symbol, stock_name") \
            .in_("symbol", unique_symbols) \
            .execute()
            
        for row in response.data:
            sym = row.get("symbol")
            name = row.get("stock_name")
            if sym and name and sym not in real_names:
                real_names[sym] = str(name).strip()
                
    except Exception as e:
        print(f"⚠️ [股名查詢警告] 無法取得真實股名: {e}")
        
    return real_names

# ==========================================
# 📊 1. 資料運算層 (具備冷啟動容錯機制)
# ==========================================
def get_tdcc_top20_diff(supabase: Client) -> Optional[Dict[str, Any]]:
    """從 Supabase 抓取 TDCC 資料，計算差值排行 (具備降級容錯)"""
    date_res = supabase.table("tdcc_history").select("date").order("date", desc=True).execute()
    unique_dates = sorted(list(set(row["date"] for row in date_res.data)), reverse=True)
    
    # 🚨 修正：即使只有 1 週資料也不拋棄，照常運行
    if len(unique_dates) == 0:
        return None 
        
    t0_date = unique_dates[0]
    # 智慧降級：如果歷史資料不夠，就拿最舊的一天來頂替
    t1_date = unique_dates[1] if len(unique_dates) >= 2 else t0_date
    t4_date = unique_dates[4] if len(unique_dates) >= 5 else unique_dates[-1]

    data_res = supabase.table("tdcc_history").select("*").in_("date", [t0_date, t1_date, t4_date]).execute()
    records = data_res.data

    if not records:
        return None

    # 利用原生字典進行樞紐轉換
    stock_map = {}
    for row in records:
        sym = row["symbol"]
        date_val = row["date"]
        
        if sym not in stock_map:
            stock_map[sym] = {}
            
        stock_map[sym][date_val] = {
            "ratio_400k": float(row.get("ratio_400k", 0) or 0),
            "ratio_1000k": float(row.get("ratio_1000k", 0) or 0)
        }

    target_symbols = list(stock_map.keys())
    real_stock_names = get_real_stock_names(supabase, target_symbols)

    results = []
    for symbol, dates_data in stock_map.items():
        if t0_date not in dates_data:
            continue
            
        r400_t0 = dates_data[t0_date]["ratio_400k"]
        r1000_t0 = dates_data[t0_date]["ratio_1000k"]

        r400_t1 = dates_data.get(t1_date, {}).get("ratio_400k", r400_t0)
        r1000_t1 = dates_data.get(t1_date, {}).get("ratio_1000k", r1000_t0)
        r400_t4 = dates_data.get(t4_date, {}).get("ratio_400k", r400_t0)
        r1000_t4 = dates_data.get(t4_date, {}).get("ratio_1000k", r1000_t0)

        diff_400_1w = round(r400_t0 - r400_t1, 2)
        diff_400_4w = round(r400_t0 - r400_t4, 2)
        diff_1000_1w = round(r1000_t0 - r1000_t1, 2)
        diff_1000_4w = round(r1000_t0 - r1000_t4, 2)

        if diff_400_4w == 0 and diff_1000_4w == 0:
            continue

        results.append({
            "symbol": symbol,
            "name": real_stock_names.get(symbol, "未知股名"), 
            "diff_400_1w": diff_400_1w,
            "diff_400_4w": diff_400_4w,
            "diff_1000_1w": diff_1000_1w,
            "diff_1000_4w": diff_1000_4w
        })

    top_20 = sorted(results, key=lambda x: x["diff_400_4w"], reverse=True)[:20]
    return {"date": t0_date, "data": top_20}


def get_single_stock_tdcc(supabase: Client, symbol: str) -> Optional[Dict[str, Any]]:
    """查詢單一股票 TDCC 變化 (具備降級容錯)"""
    date_res = supabase.table("tdcc_history").select("date").order("date", desc=True).execute()
    unique_dates = sorted(list(set(row["date"] for row in date_res.data)), reverse=True)
    
    if len(unique_dates) == 0: 
        return None
        
    t0 = unique_dates[0]
    t1 = unique_dates[1] if len(unique_dates) >= 2 else t0
    t2 = unique_dates[2] if len(unique_dates) >= 3 else t1
    t4 = unique_dates[4] if len(unique_dates) >= 5 else unique_dates[-1]

    target_dates = list(set([t0, t1, t2, t4]))

    data_res = supabase.table("tdcc_history").select("*").eq("symbol", symbol).in_("date", target_dates).execute()
    records = data_res.data
    
    # 🚨 修正：哪怕只有一筆資料，也要允許渲染
    if not records: 
        return None

    date_map = {}
    for row in records:
        date_map[row["date"]] = {
            "ratio_400k": float(row.get("ratio_400k", 0) or 0),
            "ratio_1000k": float(row.get("ratio_1000k", 0) or 0)
        }

    # 如果歷史日期沒資料，以最新的資料頂替 (讓相減結果自動歸零)
    def get_ratio(d_str: str, key: str) -> float:
        if d_str not in date_map:
            return date_map.get(t0, {}).get(key, 0.0)
        return date_map.get(d_str, {}).get(key, 0.0)

    real_stock_names = get_real_stock_names(supabase, [symbol])
    stock_name = real_stock_names.get(symbol, "未知股名")

    return {
        "sid": symbol,
        "name": stock_name, 
        "price": 0.0,
        "tdcc": {
            "1w": {
                "holders_400": round(get_ratio(t0, "ratio_400k") - get_ratio(t1, "ratio_400k"), 2),
                "holders_1000": round(get_ratio(t0, "ratio_1000k") - get_ratio(t1, "ratio_1000k"), 2)
            },
            "2w": {
                "holders_400": round(get_ratio(t0, "ratio_400k") - get_ratio(t2, "ratio_400k"), 2),
                "holders_1000": round(get_ratio(t0, "ratio_1000k") - get_ratio(t2, "ratio_1000k"), 2)
            },
            "4w": {
                "holders_400": round(get_ratio(t0, "ratio_400k") - get_ratio(t4, "ratio_400k"), 2),
                "holders_1000": round(get_ratio(t0, "ratio_1000k") - get_ratio(t4, "ratio_1000k"), 2)
            }
        }
    }

# ==========================================
# 🎨 2. 視圖渲染層 (Flex Message Builders)
# ==========================================

def build_tdcc_top20_flex(parsed_data: Dict[str, Any]) -> Dict[str, Any]:
    latest_date = parsed_data["date"]
    formatted_date = f"{latest_date[:4]}/{latest_date[4:6]}/{latest_date[6:]}"
    top_stocks = parsed_data["data"]

    def format_diff_str(diff_1w: float, diff_4w: float) -> str:
        s_1w = f"+{diff_1w:.2f}%" if diff_1w > 0 else f"{diff_1w:.2f}%"
        s_4w = f"+{diff_4w:.2f}%" if diff_4w > 0 else f"{diff_4w:.2f}%"
        return f"{s_1w} / {s_4w}"

    def get_color_by_trend(diff_4w: float) -> str:
        if diff_4w > 0: return "#D9534F"
        if diff_4w < 0: return "#5CB85C"
        return "#888888"                  

    flex_msg = {
        "type": "bubble", "size": "mega",
        "header": {
            "type": "box", "layout": "vertical", "backgroundColor": "#1A2A3A", "paddingAll": "md",
            "contents": [
                {"type": "text", "text": "📊 大戶千張 / 400張籌碼變化 TOP 排行", "weight": "bold", "color": "#FFFFFF", "size": "sm"},
                {"type": "text", "text": f"基準日期: {formatted_date} (依 4 週 400張增幅排序)", "color": "#CCCCCC", "size": "xxs", "margin": "xs"}
            ]
        },
        "body": {
            "type": "box", "layout": "vertical", "paddingAll": "md",
            "contents": [
                {
                    "type": "box", "layout": "horizontal", "alignItems": "center",
                    "contents": [
                        {"type": "text", "text": "代號/股名", "size": "xxs", "color": "#888888", "flex": 3},
                        {"type": "text", "text": "400張 (1週/4週)", "size": "xxs", "color": "#888888", "flex": 4, "align": "center"},
                        {"type": "text", "text": "千張 (1週/4週)", "size": "xxs", "color": "#888888", "flex": 4, "align": "end"}
                    ]
                },
                {"type": "separator", "margin": "xs"}
            ]
        }
    }

    rows_container = {"type": "box", "layout": "vertical", "margin": "xs", "contents": []}
    
    for stock in top_stocks[:15]:
        str_400 = format_diff_str(stock["diff_400_1w"], stock["diff_400_4w"])
        str_1000 = format_diff_str(stock["diff_1000_1w"], stock["diff_1000_4w"])
        row_color = get_color_by_trend(stock["diff_400_4w"])

        row = {
            "type": "box", "layout": "horizontal", "margin": "xs", "alignItems": "center",
            "contents": [
                {"type": "text", "text": f"{stock['symbol']} {stock['name']}".strip(), "weight": "bold", "size": "xxs", "flex": 3, "color": "#333333", "wrap": False},
                {"type": "text", "text": str_400, "size": "xxs", "flex": 4, "align": "center", "color": row_color, "wrap": False},
                {"type": "text", "text": str_1000, "size": "xxs", "flex": 4, "align": "end", "color": row_color, "wrap": False}
            ]
        }
        rows_container["contents"].append(row)

    # 🚨 若無資料 (例如剛上線第一週，差值皆為 0 被濾掉)，補上提示訊息
    if not rows_container["contents"]:
        rows_container["contents"].append({
            "type": "text", "text": "⚠️ 資料庫正在累積歷史數據，需等待次週排程後方可顯示增減排行。",
            "color": "#888888", "size": "xs", "align": "center", "margin": "md", "wrap": True
        })

    flex_msg["body"]["contents"].append(rows_container)
    return flex_msg


def generate_stock_tdcc_flex(stock_data: Dict[str, Any]) -> Dict[str, Any]:
    sid = stock_data.get("sid", "")
    name = stock_data.get("name", "")
    price = stock_data.get("price", 0.0)
    tdcc = stock_data.get("tdcc", {})

    def format_diff(val: float) -> Dict[str, str]:
        if val > 0: return {"text": f"+{val:.2f}%", "color": "#D9534F"}
        elif val < 0: return {"text": f"{val:.2f}%", "color": "#5CB85C"}
        return {"text": "-", "color": "#888888"}

    body_contents = [
        {
            "type": "box", "layout": "horizontal", "paddingBottom": "sm", "alignItems": "center",
            "contents": [
                {"type": "text", "text": "區間", "size": "xs", "color": "#94A3B8", "flex": 2},
                {"type": "text", "text": "400張大戶", "size": "xs", "color": "#94A3B8", "align": "end", "flex": 3},
                {"type": "text", "text": "1000張大戶", "size": "xs", "color": "#94A3B8", "align": "end", "flex": 3}
            ]
        },
        {"type": "separator", "color": "#CBD5E1", "margin": "sm"}
    ]

    for label, key in [("1 週", "1w"), ("2 週", "2w"), ("4 週", "4w")]:
        period_data = tdcc.get(key, {})
        diff_400 = format_diff(period_data.get("holders_400", 0.0))
        diff_1000 = format_diff(period_data.get("holders_1000", 0.0))

        row = {
            "type": "box", "layout": "horizontal", "margin": "md", "alignItems": "center",
            "contents": [
                {"type": "text", "text": label, "size": "sm", "color": "#333333", "weight": "bold", "flex": 2},
                {"type": "text", "text": diff_400["text"], "size": "sm", "color": diff_400["color"], "weight": "bold", "align": "end", "flex": 3},
                {"type": "text", "text": diff_1000["text"], "size": "sm", "color": diff_1000["color"], "weight": "bold", "align": "end", "flex": 3}
            ]
        }
        body_contents.append(row)

    flex_msg = {
        "type": "bubble", "size": "mega",
        "header": {
            "type": "box", "layout": "vertical", "backgroundColor": "#1A2A3A", "paddingAll": "md",
            "contents": [
                {"type": "text", "text": "📊 個股籌碼 X 光機", "color": "#38BDF8", "weight": "bold", "size": "sm"},
                {
                    "type": "box", "layout": "horizontal", "margin": "md", "alignItems": "center",
                    "contents": [
                        {"type": "text", "text": f"{sid} {name}".strip(), "color": "#FFFFFF", "weight": "bold", "size": "xl", "flex": 1},
                        {"type": "text", "text": f"{price}" if price > 0 else "-", "color": "#D9534F" if price > 0 else "#FFFFFF", "weight": "bold", "size": "xl", "align": "end"}
                    ]
                }
            ]
        },
        "body": {
            "type": "box", "layout": "vertical", "paddingAll": "lg",
            "contents": body_contents
        }
    }
    
    return flex_msg