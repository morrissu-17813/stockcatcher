"""Cached read-only cross-market quotes. Provider failures are explicit, never filled with demo values."""
from __future__ import annotations
import json, time, urllib.request, urllib.parse
from concurrent.futures import ThreadPoolExecutor
from threading import Lock

_CACHE = {"at": 0.0, "payload": None}
_LOCK = Lock()
_ITEMS = [
    ("twii", "加權指數", "^TWII", "points"),
    ("tpex", "櫃買指數", "^TWOII", "points"),
    ("usdtwd", "美元／新台幣", "TWD=X", "TWD"),
    ("nikkei", "日經 225", "^N225", "points"),
    ("kospi", "韓國 KOSPI", "^KS11", "points"),
    ("nasdaq_future", "那斯達克期貨", "NQ=F", "points"),
    # SXF is the Taiwan Futures Exchange ticker for PHLX Semiconductor Sector Futures.
    # Yahoo Finance does not reliably cover this Taiwan-listed futures contract, so provider
    # errors remain visible instead of substituting the cash SOX index or a made-up quote.
    ("sox_future", "費半期貨（SXF）", "SXF", "points"),
]

def _quote(symbol):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol, safe='^=') }?range=1d&interval=5m"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 AIQuantLab/1.2", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=6) as response:
        payload = json.loads(response.read().decode("utf-8"))
    chart = payload.get("chart") or {}
    if chart.get("error"):
        raise RuntimeError(str(chart["error"]))
    result = (chart.get("result") or [None])[0]
    if not result:
        raise RuntimeError("資料來源未回傳報價")
    meta = result.get("meta") or {}
    quote = ((result.get("indicators") or {}).get("quote") or [{}])[0]
    closes = [float(v) for v in (quote.get("close") or []) if v is not None]
    value = closes[-1] if closes else meta.get("regularMarketPrice")
    previous = meta.get("chartPreviousClose") or meta.get("previousClose")
    if value is None:
        raise RuntimeError("沒有有效最新價格")
    change = ((float(value) / float(previous)) - 1) * 100 if previous else None
    return float(value), change, "Yahoo Finance chart API", meta.get("currency"), closes[-24:]

def _taifex_sxf_quote():
    """Read TAIFEX's official daily futures report for SXF, without calling it tick real-time."""
    url = "https://openapi.taifex.com.tw/v1/DailyMarketReportFut"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 AIQuantLab/1.2", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=6) as response:
        payload = json.loads(response.read().decode("utf-8"))
    rows = payload if isinstance(payload, list) else (payload.get("data") or payload.get("result") or payload.get("results") or [])
    def get_field(row, *names):
        lookup = {str(k).strip().lower().replace(" ", ""): v for k, v in row.items()}
        for name in names:
            key = name.strip().lower().replace(" ", "")
            if key in lookup and lookup[key] not in (None, "", "-"):
                return lookup[key]
        return None
    eligible = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        contract = str(get_field(row, "Contract", "商品代號", "契約") or "").strip().upper()
        if contract != "SXF":
            continue
        month = str(get_field(row, "ContractMonth(Week)", "ContractMonth", "契約月份") or "")
        session = str(get_field(row, "TradingSession", "交易時段") or "")
        eligible.append((str(get_field(row, "Date", "日期") or ""), month, session, row))
    if not eligible:
        raise RuntimeError("TAIFEX 日報未回傳 SXF 契約資料")
    eligible.sort(key=lambda item: (item[0], item[2].lower(), item[1]), reverse=True)
    row = eligible[0][3]
    value_raw = get_field(row, "Last", "Close", "SettlementPrice", "結算價", "收盤價")
    try:
        value = float(str(value_raw).replace(",", ""))
    except (TypeError, ValueError):
        raise RuntimeError("TAIFEX SXF 日報沒有有效的最新價／收盤價")
    change_raw = get_field(row, "Change(%)", "Change%", "ChangePct", "ChangePercent", "漲跌幅")
    try:
        if change_raw is None:
            change = None
        else:
            change_text = str(change_raw).replace("%", "").replace(",", "").strip()
            negative_arrow = change_text.startswith("▼")
            change_text = change_text.lstrip("▲▼+ ")
            change = float(change_text) * (-1 if negative_arrow else 1)
    except (TypeError, ValueError):
        change = None
    # This official endpoint is a daily report, not tick-by-tick streaming data.
    return value, change, "TAIFEX OpenAPI · 日報（非逐筆即時）", "TWD", [value]

def _load_one(item):
    key, name, symbol, unit = item
    try:
        value, change, source, currency, history = _taifex_sxf_quote() if key == "sox_future" else _quote(symbol)
        return {"key": key, "name": name, "symbol": symbol, "value": value, "change_pct": change,
                "unit": unit, "source": source, "currency": currency, "history": history, "ok": True}, None
    except Exception as exc:
        message = f"{type(exc).__name__}: {exc}"
        provider = "TAIFEX OpenAPI（日報）" if key == "sox_future" else "Yahoo Finance chart API"
        if key == "sox_future":
            message = f"TAIFEX SXF 日報暫時無法取得：{message}；不以 SOX 現貨代替"
        row = {"key": key, "name": name, "symbol": symbol, "value": None, "change_pct": None,
               "unit": unit, "source": provider, "history": [], "ok": False, "error": message}
        return row, {"key": key, "name": name, "error": message}

def get_benchmarks(force=False):
    with _LOCK:
        if not force and _CACHE["payload"] is not None and time.time() - _CACHE["at"] < 60:
            return _CACHE["payload"]
        # Fetch all seven quote cards concurrently so one unavailable provider doesn't cause
        # seven serial six-second waits before the rest of the dashboard can render.
        with ThreadPoolExecutor(max_workers=len(_ITEMS)) as pool:
            results = list(pool.map(_load_one, _ITEMS))
        items = [pair[0] for pair in results]
        errors = [pair[1] for pair in results if pair[1]]
        payload = {"items": items, "errors": errors, "updated_at": time.time(), "cache_seconds": 60}
        _CACHE.update(at=time.time(), payload=payload)
        return payload
