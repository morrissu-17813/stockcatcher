"""Cache-first daily candles for the AI Quant Lab technical chart.
Reads the sibling StockCatcher tianji_3k/cache/daily JSON files first; API fallback is used only when fewer than 60 usable bars are cached.
"""
from __future__ import annotations
import json, os, time, urllib.parse, urllib.request, urllib.error
from datetime import date, timedelta
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_CACHE_DIR = _ROOT / 'tianji_3k' / 'cache' / 'daily'
_CACHE: dict[str, tuple[float, dict]] = {}
_CACHE_TTL = 600

def _num(row, *keys):
    for key in keys:
        val=row.get(key)
        if val not in (None, ''):
            try: return float(val)
            except (TypeError, ValueError): pass
    return 0.0

def _normalize(raw, symbol):
    if isinstance(raw, dict): raw=raw.get('data', raw.get('result', raw.get('rows', [])))
    out=[]
    if not isinstance(raw, list): return out
    for row in raw:
        if not isinstance(row, dict): continue
        d=str(row.get('date') or row.get('Date') or row.get('trade_date') or '')[:10]
        o=_num(row,'open','Open'); h=_num(row,'max','high','High'); l=_num(row,'min','low','Low'); c=_num(row,'close','Close')
        vol=_num(row,'Trading_Volume','volume','Volume')
        if not vol and row.get('volume_lots') is not None: vol=_num(row,'volume_lots')*1000
        if len(d)!=10 or min(o,h,l,c)<=0: continue
        out.append({'timestamp':d+'T00:00:00+08:00','date':d,'open':o,'high':h,'low':l,'close':c,'volume':int(max(0,vol)),'symbol':symbol})
    unique={r['date']:r for r in out}
    return [unique[k] for k in sorted(unique)]

def _read_cache(symbol):
    if not _CACHE_DIR.is_dir(): return []
    matches=sorted(_CACHE_DIR.glob(f'TaiwanStockPrice_{symbol}_*.json'),key=lambda p:p.stat().st_mtime,reverse=True)
    all_rows=[]
    for path in matches:
        try: all_rows.extend(_normalize(json.loads(path.read_text(encoding='utf-8')),symbol))
        except (OSError,ValueError,json.JSONDecodeError): continue
    unique={r['date']:r for r in all_rows}
    # only completed daily candles; never mistake today's partial daily bar for history.
    today=date.today().isoformat()
    return [unique[k] for k in sorted(unique) if k < today]

def _fetch_api(symbol):
    token=os.getenv('FINMIND_TOKEN') or os.getenv('FINMIND_API_TOKEN') or os.getenv('FINMIND_API_KEY') or ''
    start=(date.today()-timedelta(days=420)).isoformat(); end=date.today().isoformat()
    if token:
        query=urllib.parse.urlencode({'dataset':'TaiwanStockPrice','data_id':symbol,'start_date':start,'end_date':end,'token':token})
        url='https://api.finmindtrade.com/api/v4/data?'+query
        req=urllib.request.Request(url,headers={'User-Agent':'AIQuantLab/1.3','Accept':'application/json'})
        with urllib.request.urlopen(req,timeout=10) as res: payload=json.loads(res.read().decode('utf-8'))
        if payload.get('status') not in (None,200,'200'): raise RuntimeError(f"FinMind status {payload.get('status')}")
        return _normalize(payload.get('data',[]),symbol)
    # Public fallback only if FinMind is not configured.
    yahoo_symbol=symbol if symbol.endswith(('.TW','.TWO')) else symbol+'.TW'
    url=f'https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(yahoo_symbol,safe=".")}?range=2y&interval=1d&events=history'
    req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0 AIQuantLab/1.3','Accept':'application/json'})
    with urllib.request.urlopen(req,timeout=10) as res: payload=json.loads(res.read().decode('utf-8'))
    chart=payload.get('chart') or {}; results=chart.get('result') or []
    if not results: raise RuntimeError(f"Yahoo history unavailable for {symbol}: {chart.get('error')}")
    result=results[0]; timestamps=result.get('timestamp') or []; quote=((result.get('indicators') or {}).get('quote') or [{}])[0]; out=[]
    import datetime as dt
    for i,ts in enumerate(timestamps):
        try:
            o=quote['open'][i]; h=quote['high'][i]; l=quote['low'][i]; c=quote['close'][i]; v=quote['volume'][i]
            if None in (o,h,l,c): continue
            day=dt.datetime.fromtimestamp(ts,dt.timezone.utc).date().isoformat()
            if day >= end: continue
            out.append({'timestamp':day+'T00:00:00+08:00','date':day,'open':float(o),'high':float(h),'low':float(l),'close':float(c),'volume':int(v or 0),'symbol':symbol})
        except (IndexError,TypeError,ValueError,KeyError,OverflowError): continue
    return out

def get_history(symbol, limit=260):
    symbol=''.join(ch for ch in str(symbol).strip().upper().replace('.TW','').replace('.TWO','') if ch.isalnum())
    if not symbol: raise ValueError('symbol is required')
    cached=_CACHE.get(symbol)
    if cached and time.monotonic()-cached[0] < _CACHE_TTL: return dict(cached[1])
    rows=_read_cache(symbol); source='tianji_3k/cache/daily'
    # Prefer the shared production cache. Fetch only when fewer than 60 bars are available.
    if len(rows)<60:
        fetched=_fetch_api(symbol)
        merged={r['date']:r for r in rows}
        merged.update({r['date']:r for r in fetched})
        rows=[merged[k] for k in sorted(merged)]
        source='cache + FinMind API' if os.getenv('FINMIND_TOKEN') or os.getenv('FINMIND_API_TOKEN') or os.getenv('FINMIND_API_KEY') else 'Yahoo Finance daily API fallback'
    rows=rows[-max(60,min(int(limit),520)):]
    if len(rows)<2: raise RuntimeError(f'歷史 K 線不足：{symbol} 只有 {len(rows)} 根；cache 與 API 均未取得足夠資料')
    result={'symbol':symbol,'source':source,'bars':len(rows),'latest_date':rows[-1]['date'],'candles':rows}
    _CACHE[symbol]=(time.monotonic(),result)
    return dict(result)
