"""Read-only Taiwan-stock market adapters. Fugle is preferred when configured; Yahoo is fallback."""
from __future__ import annotations
import json, os, time, urllib.request, urllib.error, urllib.parse
from datetime import datetime, timezone
from typing import Any

DEFAULT_WATCHLIST = [
    {"symbol":"2330", "name":"台積電"},
    {"symbol":"2317", "name":"鴻海"},
    {"symbol":"2454", "name":"聯發科"},
    {"symbol":"2382", "name":"廣達"},
    {"symbol":"3231", "name":"緯創"},
]
class MarketDataError(RuntimeError): pass

class _Http:
    def __init__(self, timeout=8): self.timeout=timeout
    def get(self, url, headers=None):
        req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0 AIQuantLab/1.1", "Accept":"application/json", **(headers or {})})
        try:
            with urllib.request.urlopen(req,timeout=self.timeout) as res: return json.loads(res.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail=exc.read().decode("utf-8","replace")[:250]
            raise MarketDataError(f"HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError,TimeoutError,json.JSONDecodeError) as exc: raise MarketDataError(str(exc)) from exc

class FugleChartClient:
    """Fugle REST candles + quote; credentials stay server-side."""
    def __init__(self, api_key=None, timeout=8):
        self.api_key=api_key or os.getenv("FUGLE_API_KEY") or os.getenv("FUGLE_API_TOKEN") or os.getenv("FUGLE_KEY")
        self.http=_Http(timeout)
    def fetch(self,symbol):
        if not self.api_key: raise MarketDataError("Fugle API key is not configured")
        code=str(symbol).replace(".TW","").replace(".TWO","")
        headers={"X-API-KEY":self.api_key}
        base="https://api.fugle.tw/marketdata/v1.0/stock/intraday"
        candles_data=self.http.get(f"{base}/candles/{urllib.parse.quote(code)}?timeframe=1",headers)
        raw=candles_data.get("data") or []
        candles=[]
        for item in raw:
            try:
                close=float(item["close"]); stamp=str(item.get("date") or item.get("time"))
                if close<=0: continue
                candles.append({"timestamp":stamp,"close":close,"open":float(item.get("open") or close),"high":float(item.get("high") or close),"low":float(item.get("low") or close),"volume":int(item.get("volume") or 0)})
            except (TypeError,ValueError,KeyError): continue
        if not candles: raise MarketDataError(f"{code}: Fugle returned no usable intraday candles")
        # Quote endpoint provides lastPrice/previousClose for accurate daily change.
        quote=self.http.get(f"{base}/quote/{urllib.parse.quote(code)}",headers)
        price=float(quote.get("lastPrice") or candles[-1]["close"])
        prev=quote.get("previousClose") or quote.get("referencePrice") or quote.get("previous_close")
        prev=float(prev) if prev not in (None,"") else None
        closes=[c["close"] for c in candles]; vols=[c["volume"] for c in candles[-21:-1] if c["volume"]>0]
        avg=sum(vols)/len(vols) if vols else 0
        stamp=candles[-1]["timestamp"]
        try:
            dt=datetime.fromisoformat(stamp.replace("Z","+00:00")); age=max(0,int((datetime.now(dt.tzinfo or timezone.utc)-dt).total_seconds()))
        except Exception: age=0
        return {"symbol":code,"name":quote.get("name") or candles_data.get("name") or code,"currency":"TWD","price":price,"previous_close":prev,"change_pct":((price/prev)-1)*100 if prev else None,"sma5":sum(closes[-5:])/len(closes[-5:]),"sma20":sum(closes[-20:])/len(closes[-20:]),"volume":candles[-1]["volume"],"volume_avg20":avg,"volume_ratio":candles[-1]["volume"]/avg if avg else None,"market_timestamp":stamp,"data_age_seconds":age,"stale":age>1200,"source":"Fugle Market Data API","interval":"1m","candles":candles[-240:]}

class YahooChartClient:
    """Public chart API fallback; its availability/delay is not guaranteed."""
    def __init__(self, timeout: float = 8, min_interval: float = 1.0): self.timeout=timeout; self.min_interval=min_interval; self._last_request=0.0; self.http=_Http(timeout)
    def fetch(self, symbol: str) -> dict[str, Any]:
        sym=str(symbol)
        if not sym.endswith((".TW",".TWO")): sym += ".TW"
        wait=self.min_interval-(time.monotonic()-self._last_request)
        if wait>0: time.sleep(wait)
        url=f'https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(sym,safe=".")}?range=1d&interval=1m&includePrePost=false'
        self._last_request=time.monotonic(); data=self.http.get(url)
        chart=data.get('chart') or {}
        if chart.get('error'): raise MarketDataError(str(chart['error']))
        results=chart.get('result') or []
        if not results: raise MarketDataError(f'{sym}: provider returned no chart data')
        root=results[0]; meta=root.get('meta') or {}; timestamps=root.get('timestamp') or []; q=((root.get('indicators') or {}).get('quote') or [{}])[0]
        candles=[]
        for i,ts in enumerate(timestamps):
            try:
                if i>=len(q.get('close') or []) or q['close'][i] is None: continue
                close=float(q['close'][i]); stamp=datetime.fromtimestamp(int(ts),timezone.utc).astimezone().isoformat(timespec='seconds')
                candles.append({'timestamp':stamp,'close':close,'open':float((q.get('open') or [])[i] or close),'high':float((q.get('high') or [])[i] or close),'low':float((q.get('low') or [])[i] or close),'volume':int((q.get('volume') or [])[i] or 0)})
            except (IndexError,TypeError,ValueError,OverflowError): continue
        if not candles: raise MarketDataError(f'{sym}: no usable candles')
        closes=[x['close'] for x in candles]; vols=[x['volume'] for x in candles[-21:-1] if x['volume']>0]; avg=sum(vols)/len(vols) if vols else 0
        prev=meta.get('chartPreviousClose') or meta.get('previousClose'); stamp=candles[-1]['timestamp']
        age=max(0,int(time.time()-int(timestamps[-1]))) if timestamps else 0
        return {'symbol':sym,'name':meta.get('longName') or meta.get('shortName') or sym,'currency':meta.get('currency','TWD'),'price':closes[-1],'previous_close':prev,'change_pct':((closes[-1]/float(prev))-1)*100 if prev else None,'sma5':sum(closes[-5:])/len(closes[-5:]),'sma20':sum(closes[-20:])/len(closes[-20:]),'volume':candles[-1]['volume'],'volume_avg20':avg,'volume_ratio':candles[-1]['volume']/avg if avg else None,'market_timestamp':stamp,'data_age_seconds':age,'stale':age>1200,'source':'Yahoo Finance chart API (fallback)','interval':'1m','candles':candles[-240:]}

def build_market_client():
    if os.getenv("FUGLE_API_KEY") or os.getenv("FUGLE_API_TOKEN") or os.getenv("FUGLE_KEY"):
        return FugleChartClient()
    return YahooChartClient()
