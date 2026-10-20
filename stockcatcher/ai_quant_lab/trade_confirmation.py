"""Isolated copy of Tianji 3K intraday confirmation chain for AI Quant Lab.

No production imports, no broker integration, no local durable storage.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone, time as dtime
from decimal import Decimal
import json, os, time, urllib.parse, urllib.request, urllib.error

TAIPEI = timezone(timedelta(hours=8))

@dataclass(frozen=True)
class RadarSnapshot:
    symbol: str
    snapshot_id: str
    data_identity: str
    current_price: float
    previous_close: float
    today_open: float
    up_pct: float
    is_traded: bool = True
    payload_hash: str = ''

class RadarStateMachine:
    """Two distinct valid market snapshots required; duplicate identities never confirm."""
    def __init__(self):
        self.state='WATCHING'; self.last_snapshot_id=''; self.pending_count=0
        self.trigger_count=0; self.last_trigger_price=0.0; self.seen=set()
    def evaluate(self, snap: RadarSnapshot, breakout_level: float, gain_threshold_pct=4.0, buffer_pct=0.3):
        ident=snap.data_identity or snap.payload_hash
        if snap.snapshot_id == self.last_snapshot_id or ident in self.seen:
            return False, 'DUPLICATE_SNAPSHOT'
        self.last_snapshot_id=snap.snapshot_id; self.seen.add(ident)
        effective=snap.current_price >= breakout_level*(1+buffer_pct/100)
        valid=(snap.is_traded and snap.previous_close>0 and snap.today_open>0 and
               snap.current_price>snap.today_open and snap.up_pct>=gain_threshold_pct and effective)
        if self.state=='TRIGGERED':
            if not valid: self.state='INVALIDATED'; self.pending_count=0; return False,'TRIGGER_INVALIDATED'
            return False,'ALREADY_TRIGGERED_WAIT_REARM'
        if valid:
            self.state='BREAKOUT_PENDING'; self.pending_count+=1
            if self.pending_count>=2:
                self.pending_count=0; self.trigger_count+=1; self.last_trigger_price=snap.current_price
                self.state='TRIGGERED'; return True,'EFFECTIVE_BREAKOUT'
            return False,'FIRST_VALID_CONFIRMATION'
        self.pending_count=0
        self.state='WATCHING' if self.state!='INVALIDATED' else 'COOLDOWN'
        return False,'BREAKOUT_CONDITIONS_NOT_MET'

class FinMindHistoryProvider:
    """Selective history fetch only for dynamic candidates; memory cache only."""
    def __init__(self, token=None, timeout=8, cache_seconds=21600):
        self.token=token or os.getenv('FINMIND_TOKEN') or os.getenv('FINMIND_API_TOKEN') or os.getenv('FINMIND_TOKEN_ID')
        self.timeout=timeout; self.cache_seconds=cache_seconds; self.cache={}
    def _get(self, symbol):
        if not self.token: raise RuntimeError('FINMIND_TOKEN_NOT_CONFIGURED')
        end=datetime.now(TAIPEI).date(); start=end-timedelta(days=150)
        query=urllib.parse.urlencode({'dataset':'TaiwanStockPrice','data_id':symbol,'start_date':start.isoformat(),'end_date':end.isoformat(),'token':self.token})
        req=urllib.request.Request('https://api.finmindtrade.com/api/v4/data?'+query,headers={'User-Agent':'AIQuantLab/1.0','Accept':'application/json'})
        try:
            with urllib.request.urlopen(req,timeout=self.timeout) as r: payload=json.loads(r.read().decode())
        except (urllib.error.URLError,TimeoutError,json.JSONDecodeError) as e: raise RuntimeError(f'FINMIND_HISTORY_ERROR:{type(e).__name__}') from e
        if payload.get('status') not in (200,'200',None): raise RuntimeError(f"FINMIND_STATUS_{payload.get('status')}")
        rows=payload.get('data') or []
        clean=[]
        for r in rows:
            try:
                row={'date':str(r['date'])[:10], 'open':float(r.get('open') or 0), 'high':float(r.get('max') or r.get('high') or 0), 'low':float(r.get('min') or r.get('low') or 0), 'close':float(r.get('close') or 0), 'volume_lots':float(r.get('Trading_Volume') or r.get('volume') or 0)/1000.0}
                if min(row['open'],row['high'],row['low'],row['close'])>0: clean.append(row)
            except (KeyError,TypeError,ValueError): continue
        clean.sort(key=lambda x:x['date'])
        # Only completed daily bars are allowed as the historical baseline.
        clean=[row for row in clean if row['date'] < end.isoformat()]
        if len(clean)<61: raise RuntimeError(f'HISTORY_INSUFFICIENT:{len(clean)}')
        return clean[-100:]
    def context(self,symbol):
        cached=self.cache.get(str(symbol))
        if cached and time.monotonic()-cached[0]<self.cache_seconds: return dict(cached[1])
        bars=self._get(str(symbol)); closes=[x['close'] for x in bars]
        ma20=sum(closes[-20:])/20; ma60=sum(closes[-60:])/60; ma20_prev=sum(closes[-21:-1])/20
        vma5=sum(x['volume_lots'] for x in bars[-5:])/5
        k0,k1,k2=bars[-1],bars[-2],bars[-3]
        result={'symbol':str(symbol),'source':'FinMind TaiwanStockPrice','history_bars':len(bars),'source_data_date':k0['date'],
                'ma20':ma20,'ma60':ma60,'ma20_prev':ma20_prev,'vma5_lots':vma5,
                'previous_close':k0['close'],'k1_high':k0['high'],'k2_high':k1['high'],
                'breakout_level':max(k0['high'],k1['high']),
                'stage1_pass':bool(k0['close']>ma20 and k0['close']>ma60 and ma20>ma60 and ma20>ma20_prev),
                'liquidity_pass':vma5>=1000}
        self.cache[str(symbol)]=(time.monotonic(),result)
        return dict(result)

class FugleFiveMinuteProvider:
    """Fetch completed Fugle 5m candles; forming candle is excluded."""
    def __init__(self, api_key=None, timeout=8):
        self.api_key=api_key or os.getenv('FUGLE_API_KEY') or os.getenv('FUGLE_API_TOKEN') or os.getenv('FUGLE_KEY')
        self.timeout=timeout; self.cache={}
    def bars(self,symbol):
        if not self.api_key: raise RuntimeError('FUGLE_API_KEY_NOT_CONFIGURED')
        cached=self.cache.get(str(symbol))
        if cached and time.monotonic()-cached[0]<15: return [dict(x) for x in cached[1]]
        url=f'https://api.fugle.tw/marketdata/v1.0/stock/intraday/candles/{urllib.parse.quote(str(symbol))}?timeframe=5'
        req=urllib.request.Request(url,headers={'X-API-KEY':self.api_key,'Accept':'application/json','User-Agent':'AIQuantLab/1.0'})
        try:
            with urllib.request.urlopen(req,timeout=self.timeout) as r: payload=json.loads(r.read().decode())
        except urllib.error.HTTPError as e: raise RuntimeError(f'FUGLE_HTTP_{e.code}') from e
        except (urllib.error.URLError,TimeoutError,json.JSONDecodeError) as e: raise RuntimeError(f'FUGLE_5M_ERROR:{type(e).__name__}') from e
        rows=payload.get('data') or payload.get('candles') or []; now=datetime.now(TAIPEI); out=[]
        for x in rows if isinstance(rows,list) else []:
            try:
                dt=datetime.fromisoformat(str(x.get('date') or x.get('time')).replace('Z','+00:00'))
                if dt.tzinfo is None: dt=dt.replace(tzinfo=TAIPEI)
                dt=dt.astimezone(TAIPEI)
                if dt+timedelta(minutes=5)>now: continue
                bar={'date':dt.isoformat(timespec='seconds'),'open':float(x['open']),'high':float(x['high']),'low':float(x['low']),'close':float(x['close']),'volume':float(x['volume'])}
                if min(bar['open'],bar['high'],bar['low'],bar['close'])>0: out.append(bar)
            except (KeyError,TypeError,ValueError): continue
        out.sort(key=lambda x:x['date']); self.cache[str(symbol)]=(time.monotonic(),out)
        return [dict(x) for x in out]
    def confirm_micro_breakout(self,symbol, min_volume_ratio=1.2):
        bars=self.bars(symbol)
        if len(bars)<23: return {'passed':False,'reason':'FUGLE_5M_INSUFFICIENT_COMPLETED_BARS','bars':len(bars)}
        first,second,third=bars[-3:]; baseline=bars[-23:-3]
        avg=sum(x['volume'] for x in baseline)/len(baseline)
        if avg<=0: return {'passed':False,'reason':'FUGLE_5M_INVALID_VOLUME_BASELINE','bars':len(bars)}
        ratio=third['volume']/avg; level=max(first['high'],second['high'])
        structure=third['close']>level; volume=ratio>=min_volume_ratio
        return {'passed':bool(structure and volume),'reason':'FUGLE_5M_CONFIRMED' if structure and volume else 'FUGLE_5M_CONFIRMATION_FAILED',
                'bar_time':third['date'],'breakout_level_5m':level,'close':third['close'],'volume_ratio':ratio,
                'structure_pass':structure,'volume_pass':volume,'stop_price':min(x['low'] for x in (first,second,third)),'bars':len(bars)}

def projected_volume(cumulative_lots, observed_at, vma5_lots, min_elapsed_minutes=5.0):
    if isinstance(observed_at,str):
        observed_at=datetime.fromisoformat(observed_at.replace('Z','+00:00'))
    if observed_at.tzinfo is None: observed_at=observed_at.replace(tzinfo=TAIPEI)
    start=datetime.combine(observed_at.date(),dtime(9,0),observed_at.tzinfo); end=datetime.combine(observed_at.date(),dtime(13,30),observed_at.tzinfo)
    elapsed=max(0,min((observed_at-start).total_seconds()/60,270)); ready=elapsed>=min_elapsed_minutes
    projected=float(cumulative_lots)*270/elapsed if ready and elapsed else 0.0
    ratio=projected/float(vma5_lots) if ready and vma5_lots and float(vma5_lots)>0 else None
    return {'ready':ready,'elapsed_minutes':elapsed,'projected_volume_lots':projected,'projected_ratio':ratio,'threshold':1.5,'passed':bool(ready and ratio is not None and ratio>=1.5)}
