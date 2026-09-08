import pandas as pd
from typing import Dict, Any, Optional, List
from supabase import Client

# 💡 實務上這裡可以透過 JOIN 你的個股基本資料表來取得名稱
# 若暫時沒有，這裡用快取字典做防呆
MOCK_STOCK_NAMES = {
    "2330": "台積電", "2317": "鴻海", "2454": "聯發科", 
    "3231": "緯創", "2382": "廣達"
}

# ==========================================
# 📊 1. 資料運算層 (Data Logic)
# ==========================================

def get_tdcc_top20_diff(supabase: Client) -> Optional[Dict[str, Any]]:
    """從 Supabase 抓取 TDCC 資料，計算 1W 與 4W 差值，並回傳 Top 20"""
    # 1. 取得最近 5 週的交易資料日期
    date_res = supabase.table("tdcc_history").select("date").order("date", desc=True).execute()
    unique_dates = sorted(list(set(row["date"] for row in date_res.data)), reverse=True)
    
    if len(unique_dates) < 5:
        return None # 資料庫歷史資料不足
        
    t0_date, t1_date, t4_date = unique_dates[0], unique_dates[1], unique_dates[4]

    # 2. 撈取這三個日期的所有資料
    data_res = supabase.table("tdcc_history").select("*").in_("date", [t0_date, t1_date, t4_date]).execute()
    df = pd.DataFrame(data_res.data)

    if df.empty:
        return None

    # 3. 樞紐轉換
    pivot_400 = df.pivot(index="symbol", columns="date", values="ratio_400k").fillna(0)
    pivot_1000 = df.pivot(index="symbol", columns="date", values="ratio_1000k").fillna(0)

    results = []
    for symbol in pivot_400.index:
        try:
            r400_t0, r400_t1, r400_t4 = pivot_400.at[symbol, t0_date], pivot_400.at[symbol, t1_date], pivot_400.at[symbol, t4_date]
            r1000_t0, r1000_t1, r1000_t4 = pivot_1000.at[symbol, t0_date], pivot_1000.at[symbol, t1_date], pivot_1000.at[symbol, t4_date]

            diff_400_1w = round(r400_t0 - r400_t1, 2)
            diff_400_4w = round(r400_t0 - r400_t4, 2)
            diff_1000_1w = round(r1000_t0 - r1000_t1, 2)
            diff_1000_4w = round(r1000_t0 - r1000_t4, 2)

            if diff_400_4w == 0 and diff_1000_4w == 0:
                continue

            results.append({
                "symbol": symbol,
                "name": MOCK_STOCK_NAMES.get(symbol, ""), 
                "diff_400_1w": diff_400_1w,
                "diff_400_4w": diff_400_4w,
                "diff_1000_1w": diff_1000_1w,
                "diff_1000_4w": diff_1000_4w
            })
        except KeyError:
            continue

    # 4. 依照 400張 4週增幅 降冪排序，取 Top 20
    top_20 = sorted(results, key=lambda x: x["diff_400_4w"], reverse=True)[:20]
    return {"date": t0_date, "data": top_20}

def get_single_stock_tdcc(supabase: Client, symbol: str) -> Optional[Dict[str, Any]]:
    """查詢單一股票的 TDCC 籌碼變化 (1W, 2W, 4W)"""
    date_res = supabase.table("tdcc_history").select("date").order("date", desc=True).execute()
    unique_dates = sorted(list(set(row["date"] for row in date_res.data)), reverse=True)
    
    if len(unique_dates) < 5: return None
        
    target_dates = [unique_dates[0], unique_dates[1], unique_dates[2], unique_dates[4]]
    t0, t1, t2, t4 = target_dates

    data_res = supabase.table("tdcc_history").select("*").eq("symbol", symbol).in_("date", target_dates).execute()
    df = pd.DataFrame(data_res.data)
    
    if df.empty or len(df) < 2: return None

    df.set_index("date", inplace=True)
    def get_ratio(date_str: str, col: str) -> float:
        return float(df.at[date_str, col]) if date_str in df.index else 0.0

    return {
        "sid": symbol,
        "name": MOCK_STOCK_NAMES.get(symbol, ""), 
        "price": 0.0, # 實務需 JOIN 報價表，此處佔位
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
    """產出大戶增持 TOP 20 的 Flex Message"""
    latest_date = parsed_data["date"]
    formatted_date = f"{latest_date[:4]}/{latest_date[4:6]}/{latest_date[6:]}"
    top_stocks = parsed_data["data"]

    def format_diff_str(diff_1w: float, diff_4w: float) -> str:
        s_1w = f"+{diff_1w:.2f}%" if diff_1w > 0 else f"{diff_1w:.2f}%"
        s_4w = f"+{diff_4w:.2f}%" if diff_4w > 0 else f"{diff_4w:.2f}%"
        return f"{s_1w} / {s_4w}"

    def get_color_by_trend(diff_4w: float) -> str:
        if diff_4w > 0: return "#D9534F"  # 偏多紅
        if diff_4w < 0: return "#5CB85C"  # 偏空綠
        return "#888888"                  

    flex_msg = {
        "type": "bubble", "size": "mega",
        "header": {
            "type": "box", "layout": "vertical", "backgroundColor": "#1A2A3A", "paddingAll": "md",
            "contents": [
                {"type": "text", "text": "📊 大戶千張 / 400張籌碼變化 TOP 20", "weight": "bold", "color": "#FFFFFF", "size": "sm"},
                {"type": "text", "text": f"基準日期: {formatted_date} (依 4 週 400張增幅排序)", "color": "#CCCCCC", "size": "xxs", "margin": "xs"}
            ]
        },
        "body": {
            "type": "box", "layout": "vertical", "paddingAll": "md",
            "contents": [
                {
                    "type": "box", "layout": "horizontal",
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
    
    # 僅呈現前 15 筆，避免 LINE Payload 大小超限
    for stock in top_stocks[:15]:
        str_400 = format_diff_str(stock["diff_400_1w"], stock["diff_400_4w"])
        str_1000 = format_diff_str(stock["diff_1000_1w"], stock["diff_1000_4w"])
        row_color = get_color_by_trend(stock["diff_400_4w"])

        row = {
            "type": "box", "layout": "horizontal", "margin": "xs",
            "contents": [
                {"type": "text", "text": f"{stock['symbol']} {stock['name']}".strip(), "weight": "bold", "size": "xxs", "flex": 3, "color": "#333333", "wrap": False},
                {"type": "text", "text": str_400, "size": "xxs", "flex": 4, "align": "center", "color": row_color, "wrap": False},
                {"type": "text", "text": str_1000, "size": "xxs", "flex": 4, "align": "end", "color": row_color, "wrap": False}
            ]
        }
        rows_container["contents"].append(row)

    flex_msg["body"]["contents"].append(rows_container)
    return flex_msg

def generate_stock_tdcc_flex(stock_data: Dict[str, Any]) -> Dict[str, Any]:
    """產出單一個股籌碼 X 光機 (1W, 2W, 4W) 的 Flex Message"""
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
            "type": "box", "layout": "horizontal", "paddingBottom": "sm",
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
                        {"type": "text", "text": f"{price}", "color": "#D9534F" if price > 0 else "#FFFFFF", "weight": "bold", "size": "xl", "align": "end"}
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