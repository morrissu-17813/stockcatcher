from typing import Dict, Any, Optional, List
from supabase import Client
import logging

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
        response = supabase.table("stock_info") \
            .select("symbol, name") \
            .in_("symbol", unique_symbols) \
            .execute()
            
        for row in response.data:
            sym = row.get("symbol")
            name = row.get("name")
            if sym and name and sym not in real_names:
                real_names[sym] = str(name).strip()
                
    except Exception as e:
        logging.error(f"⚠️ [股名查詢警告] 無法取得真實股名: {e}")
        
    return real_names

# ==========================================
# 📊 1. 資料運算層 (實作嚴格過濾與分頁)
# ==========================================
def get_tdcc_top20_diff(supabase: Client) -> Optional[Dict[str, Any]]:
    """從 Supabase 抓取全市場 TDCC 資料，修復分頁排序與全域降級邏輯"""
    import logging
    
    # 1. 取得日曆錨點
    try:
        date_res = supabase.table("tdcc_history").select("date").eq("symbol", "2330").order("date", desc=True).limit(5).execute()
        unique_dates = [row["date"] for row in date_res.data]
        
        if not unique_dates:
            date_res = supabase.table("tdcc_history").select("date").order("date", desc=True).limit(5000).execute()
            unique_dates = sorted(list(set(row["date"] for row in date_res.data)), reverse=True)[:5]
    except Exception as e:
        logging.error(f"❌ [TDCC 日期查詢失敗] {e}")
        return None

    if len(unique_dates) == 0:
        return None 
        
    t0 = unique_dates[0]
    t1 = unique_dates[1] if len(unique_dates) >= 2 else None
    t4 = unique_dates[4] if len(unique_dates) >= 5 else None

    target_dates = [d for d in [t0, t1, t4] if d is not None]
    
    # 2. 🚨 修正核心 A：分頁必須加上 .order("symbol")，保證資料 100% 不漏抓
    records = []
    page_size = 1000
    
    for d in target_dates:
        offset = 0
        while True:
            try:
                res = supabase.table("tdcc_history") \
                    .select("*") \
                    .eq("date", d) \
                    .order("symbol") \
                    .range(offset, offset + page_size - 1) \
                    .execute()
                
                batch_data = res.data
                records.extend(batch_data)
                
                if len(batch_data) < page_size:
                    break
                offset += page_size
            except Exception as e:
                logging.error(f"❌ [TDCC 分頁查詢失敗] 日期: {d}, 錯誤: {e}")
                break

    if not records:
        return None

    # 3. 記憶體內對齊與樞紐運算
    stock_map = {}
    for row in records:
        sym = row["symbol"].strip()
        date_val = row["date"]
        
        # 第一層過濾：非 4 碼純數字標的直接剃除
        if not (sym.isdigit() and len(sym) == 4):
            continue
            
        if sym not in stock_map:
            stock_map[sym] = {}
        stock_map[sym][date_val] = {
            "ratio_400k": float(row.get("ratio_400k", 0) or 0),
            "ratio_1000k": float(row.get("ratio_1000k", 0) or 0)
        }

    results = []
    for symbol, dates_data in stock_map.items():
        if t0 not in dates_data:
            continue
            
        r400_t0 = dates_data[t0]["ratio_400k"]
        r1000_t0 = dates_data[t0]["ratio_1000k"]

        diff_400_1w = round(r400_t0 - dates_data[t1]["ratio_400k"], 2) if t1 and t1 in dates_data else None
        diff_400_4w = round(r400_t0 - dates_data[t4]["ratio_400k"], 2) if t4 and t4 in dates_data else None
        diff_1000_1w = round(r1000_t0 - dates_data[t1]["ratio_1000k"], 2) if t1 and t1 in dates_data else None
        diff_1000_4w = round(r1000_t0 - dates_data[t4]["ratio_1000k"], 2) if t4 and t4 in dates_data else None

        results.append({
            "symbol": symbol,
            "name": "", 
            "current_400k": r400_t0, 
            "diff_400_1w": diff_400_1w,
            "diff_400_4w": diff_400_4w,
            "diff_1000_1w": diff_1000_1w,
            "diff_1000_4w": diff_1000_4w
        })

    # 4. 🚨 修正核心 B：全域一致的降級演算法
    # 嚴格區分「差值」與「絕對佔比」，缺失資料者 (-999) 自動沉到底部
    if t4 is not None:
        results.sort(key=lambda x: x["diff_400_4w"] if x["diff_400_4w"] is not None else -999, reverse=True)
    elif t1 is not None:
        results.sort(key=lambda x: x["diff_400_1w"] if x["diff_400_1w"] is not None else -999, reverse=True)
    else:
        results.sort(key=lambda x: x["current_400k"], reverse=True)
    
    # 5. 第二層過濾：擴大 Buffer 至 100 檔，確保過濾掉下市股後仍有足夠的 TOP 20
    candidate_symbols = [item["symbol"] for item in results[:100]]
    real_stock_names = get_real_stock_names(supabase, candidate_symbols)
    
    final_top_20 = []
    for item in results:
        if item["symbol"] in real_stock_names:
            item["name"] = real_stock_names[item["symbol"]]
            final_top_20.append(item)
            
        if len(final_top_20) >= 20:
            break

    return {"date": t0, "data": final_top_20, "is_fallback": (t4 is None)}

def get_single_stock_tdcc(supabase: Client, symbol: str) -> Optional[Dict[str, Any]]:
    """查詢單一股票 TDCC 變化"""
    date_res = supabase.table("tdcc_history").select("date").eq("symbol", symbol).order("date", desc=True).limit(5).execute()
    unique_dates = [row["date"] for row in date_res.data]
    
    if len(unique_dates) == 0: 
        return None
        
    t0 = unique_dates[0]
    t1 = unique_dates[1] if len(unique_dates) >= 2 else None
    t2 = unique_dates[2] if len(unique_dates) >= 3 else None
    t4 = unique_dates[4] if len(unique_dates) >= 5 else None

    target_dates = [d for d in [t0, t1, t2, t4] if d is not None]
    data_res = supabase.table("tdcc_history").select("*").eq("symbol", symbol).in_("date", target_dates).execute()
    records = data_res.data
    
    if not records: 
        return None

    date_map = {}
    for row in records:
        date_map[row["date"]] = {
            "ratio_400k": float(row.get("ratio_400k", 0) or 0),
            "ratio_1000k": float(row.get("ratio_1000k", 0) or 0)
        }

    r400_t0 = date_map.get(t0, {}).get("ratio_400k", 0.0)
    r1000_t0 = date_map.get(t0, {}).get("ratio_1000k", 0.0)

    def calc_diff(target_t: Optional[str], key: str, current_val: float) -> Optional[float]:
        if target_t and target_t in date_map:
            return round(current_val - date_map[target_t][key], 2)
        return None

    real_stock_names = get_real_stock_names(supabase, [symbol])

    return {
        "sid": symbol,
        "name": real_stock_names.get(symbol, "未知股名"), 
        "price": 0.0,
        "tdcc": {
            "1w": {
                "holders_400": calc_diff(t1, "ratio_400k", r400_t0),
                "holders_1000": calc_diff(t1, "ratio_1000k", r1000_t0)
            },
            "2w": {
                "holders_400": calc_diff(t2, "ratio_400k", r400_t0),
                "holders_1000": calc_diff(t2, "ratio_1000k", r1000_t0)
            },
            "4w": {
                "holders_400": calc_diff(t4, "ratio_400k", r400_t0),
                "holders_1000": calc_diff(t4, "ratio_1000k", r1000_t0)
            }
        }
    }

# ==========================================
# 🎨 2. 視圖渲染層 (實作 Span 獨立紅綠上色)
# ==========================================
def build_tdcc_top20_flex(parsed_data: Dict[str, Any]) -> Dict[str, Any]:
    latest_date = parsed_data["date"]
    formatted_date = f"{latest_date[:4]}/{latest_date[4:6]}/{latest_date[6:]}"
    top_stocks = parsed_data["data"]
    is_fallback = parsed_data.get("is_fallback", False)

    # 🚨 視覺強化：利用 LINE Flex span 將正負值獨立上色
    def create_diff_spans(diff_1w: Optional[float], diff_4w: Optional[float]) -> List[Dict[str, str]]:
        def get_span(val: Optional[float]) -> Dict[str, str]:
            if val is None:
                return {"type": "span", "text": "-", "color": "#94A3B8"}
            elif val > 0:
                return {"type": "span", "text": f"+{val:.2f}%", "color": "#D9534F"} # 紅色 (增幅)
            elif val < 0:
                return {"type": "span", "text": f"{val:.2f}%", "color": "#5CB85C"} # 綠色 (減幅)
            else:
                return {"type": "span", "text": "0.00%", "color": "#94A3B8"} # 灰色 (無變化)
                
        return [
            get_span(diff_1w),
            {"type": "span", "text": " / ", "color": "#CBD5E1"},
            get_span(diff_4w)
        ]

    sort_title = "歷史累積中 (依 1 週增幅排序)" if is_fallback else "依 4 週 400張增幅排序"

    flex_msg = {
        "type": "bubble", "size": "mega",
        "header": {
            "type": "box", "layout": "vertical", "backgroundColor": "#1A2A3A", "paddingAll": "md",
            "contents": [
                {"type": "text", "text": "📊 大戶千張 / 400張籌碼變化 TOP 20", "weight": "bold", "color": "#E2E8F0", "size": "sm"},
                {"type": "text", "text": f"基準日期: {formatted_date} ({sort_title})", "color": "#94A3B8", "size": "xxs", "margin": "xs"}
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
    
    for stock in top_stocks[:20]:
        row = {
            "type": "box", "layout": "horizontal", "margin": "xs", "alignItems": "center",
            "contents": [
                {"type": "text", "text": f"{stock['symbol']} {stock['name']}".strip(), "weight": "bold", "size": "xxs", "flex": 3, "color": "#333333", "wrap": False},
                {"type": "text", "contents": create_diff_spans(stock["diff_400_1w"], stock["diff_400_4w"]), "size": "xxs", "flex": 4, "align": "center", "wrap": False},
                {"type": "text", "contents": create_diff_spans(stock["diff_1000_1w"], stock["diff_1000_4w"]), "size": "xxs", "flex": 4, "align": "end", "wrap": False}
            ]
        }
        rows_container["contents"].append(row)

    flex_msg["body"]["contents"].append(rows_container)
    return flex_msg


def generate_stock_tdcc_flex(stock_data: Dict[str, Any]) -> Dict[str, Any]:
    sid = stock_data.get("sid", "")
    name = stock_data.get("name", "")
    price = stock_data.get("price", 0.0)
    tdcc = stock_data.get("tdcc", {})

    def format_diff(val: Optional[float]) -> Dict[str, str]:
        if val is None: return {"text": "-", "color": "#94A3B8"}
        if val > 0: return {"text": f"+{val:.2f}%", "color": "#D9534F"}
        elif val < 0: return {"text": f"{val:.2f}%", "color": "#5CB85C"}
        return {"text": "0.00%", "color": "#94A3B8"}

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
        diff_400 = format_diff(period_data.get("holders_400", None))
        diff_1000 = format_diff(period_data.get("holders_1000", None))

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
                {"type": "text", "text": "📊 個股籌碼", "color": "#E2E8F0", "weight": "bold", "size": "sm"},
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