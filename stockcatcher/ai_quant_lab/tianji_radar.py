"""Isolated copy of Tianji 3K's market-wide MIS discovery concepts.

Read-only adapter: TWSE/TPEx universe metadata + TWSE MIS batched snapshots.
It does not import or mutate production tianji_3k modules/files.
"""
from __future__ import annotations
import json, re, time, urllib.parse, urllib.request, urllib.error
from datetime import datetime, timezone, timedelta

TAIPEI = timezone(timedelta(hours=8))

class RadarError(RuntimeError): pass

def _get_json(url, timeout=8, headers=None):
    req=urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0 TianjiAIQuantLab/1.0", "Accept":"application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode('utf-8'))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
        raise RadarError(f"{type(e).__name__}: {e}") from e

def _num(value):
    try:
        s=str(value or '').replace(',','').strip()
        return 0.0 if s in ('','-','--','None','null') else float(s)
    except (TypeError, ValueError): return 0.0

class TaiwanMarketRadar:
    """Market-wide MIS snapshot + low-cost Dynamic Discovery gate.

    Uses official TWSE/TPEx public endpoints for universe metadata and the
    same TWSE MIS batch endpoint used by the production radar for live quotes.
    Historical enrichment/Fugle confirmation are intentionally separate stages.
    """
    def __init__(self, timeout=8, batch_size=80, universe_ttl=21600):
        self.timeout=timeout; self.batch_size=max(1,int(batch_size)); self.universe_ttl=universe_ttl
        self.universe={}; self.universe_at=0.0; self.last_snapshot_at=None; self.last_error=None
        self.snapshot={}; self.candidates=[]; self.stats={}

    def _universe_refresh(self):
        listed=_get_json('https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL', self.timeout)
        otc=_get_json('https://www.tpex.org.tw/openapi/v1/tpex_mainboard_quotes', self.timeout)
        out={}
        for row in listed if isinstance(listed,list) else []:
            sid=str(row.get('Code','')).strip()
            if re.fullmatch(r'\d{4}',sid):
                # TWSE TradeVolume is shares; convert to lots.
                out[sid]={'symbol':sid,'name':str(row.get('Name') or sid).strip(),'market':'TWSE','exchange':'tse','security_type':'common_stock','previous_volume_lots':_num(row.get('TradeVolume'))/1000.0}
        for row in otc if isinstance(otc,list) else []:
            sid=str(row.get('SecuritiesCompanyCode','')).strip()
            if re.fullmatch(r'\d{4}',sid):
                # TPEx TradingShares is shares; convert to lots.
                out[sid]={'symbol':sid,'name':str(row.get('CompanyName') or row.get('SecuritiesCompanyName') or sid).strip(),'market':'TPEx','exchange':'otc','security_type':'common_stock','previous_volume_lots':_num(row.get('TradingShares'))/1000.0}
        if len(out)<100: raise RadarError(f'Universe snapshot suspiciously small: {len(out)}')
        self.universe=out; self.universe_at=time.monotonic()

    @staticmethod
    def _quote_time(row, received):
        date=str(row.get('d') or '').strip(); clock=str(row.get('t') or '').strip()
        if not clock: return None
        try:
            if re.fullmatch(r'\d{8}',date): dt=datetime.strptime(date+' '+clock,'%Y%m%d %H:%M:%S').replace(tzinfo=TAIPEI)
            else: dt=datetime.strptime(received.strftime('%Y%m%d')+' '+clock,'%Y%m%d %H:%M:%S').replace(tzinfo=TAIPEI)
            age=(received-dt).total_seconds()
            if age < -5 or age > 86400: return None
            return dt
        except (ValueError, TypeError): return None

    def _fetch_batch(self, rows):
        codes='|'.join(f"{self.universe[s]['exchange']}_{s}.tw" for s in rows)
        url='https://mis.twse.com.tw/stock/api/getStockInfo.jsp?'+urllib.parse.urlencode({'ex_ch':codes,'_':int(time.time()*1000)})
        payload=_get_json(url,self.timeout,headers={'Referer':'https://mis.twse.com.tw/stock/index.jsp'})
        received=datetime.now(TAIPEI); out={}
        for q in payload.get('msgArray',[]) if isinstance(payload,dict) else []:
            sid=str(q.get('c') or '').strip(); y=_num(q.get('y')); price=_num(q.get('z'))
            if sid not in self.universe or y<=0 or price<=0: continue
            qt=self._quote_time(q,received); age=max(0.0,(received-qt).total_seconds()) if qt else None
            lots=_num(q.get('v'))
            meta=self.universe[sid]
            out[sid]={**meta,'price':price,'current_price':price,'previous_close':y,'today_open':_num(q.get('o')),
                'change_pct':round((price/y-1)*100,4),'up_pct':round((price/y-1)*100,4),
                'volume_lots':lots,'cumulative_volume_lots':lots,'volume_shares':lots*1000,
                'market_timestamp':qt.isoformat(timespec='seconds') if qt else None,'observed_at':received.isoformat(timespec='seconds'),
                'data_age_seconds':round(age,1) if age is not None else None,'stale':age is None or age>60,
                'quote_time_known':qt is not None,'source':'TWSE MIS snapshot','data_identity':'|'.join([sid,str(q.get('d','')),str(q.get('t','')),str(q.get('z','')),str(q.get('v',''))])}
        return out

    def _discover(self, now):
        # Port of production DynamicDiscoveryConfig gate: candidates only, never 3K PASS.
        start=now.replace(hour=9,minute=0,second=0,microsecond=0); end=now.replace(hour=13,minute=30,second=0,microsecond=0)
        fraction=1/270 if now<=start else (1.0 if now>=end else max((now-start).total_seconds()/16200,1/270))
        found=[]
        for sid,q in self.snapshot.items():
            u=self.universe.get(sid,{})
            if q.get('stale') or q.get('security_type')!='common_stock' or u.get('previous_volume_lots',0)<1000: continue
            if q['up_pct']<3 or q['price']<=q['today_open'] or q['volume_lots']<300: continue
            pace=(q['volume_lots']/u['previous_volume_lots'])/fraction if fraction else 0
            if pace<0.8: continue
            found.append({k:q[k] for k in ('symbol','name','market','price','up_pct','volume_lots','market_timestamp','data_age_seconds','source') } | {'volume_pace_ratio':round(pace,3),'status':'DYNAMIC_CANDIDATE_NOT_3K_PASS'})
        found.sort(key=lambda x:(x['up_pct'],x['volume_pace_ratio']),reverse=True)
        return found

    def scan(self):
        try:
            if not self.universe or time.monotonic()-self.universe_at>self.universe_ttl: self._universe_refresh()
            symbols=list(self.universe); merged={}; failures=0; batch_count=0
            for i in range(0,len(symbols),self.batch_size):
                batch=symbols[i:i+self.batch_size]; batch_count+=1
                try: merged.update(self._fetch_batch(batch))
                except Exception: failures+=1
            if not merged: raise RadarError('MIS returned no usable market quotes')
            self.snapshot=merged; now=datetime.now(TAIPEI); self.last_snapshot_at=now.isoformat(timespec='seconds'); self.last_error=None
            self.candidates=self._discover(now)
            self.stats={'universe_symbols':len(self.universe),'snapshot_symbols':len(merged),'batches':batch_count,'failed_batches':failures,'dynamic_candidates':len(self.candidates),'as_of':self.last_snapshot_at,'source':'TWSE MIS + TWSE/TPEx OpenAPI'}
        except Exception as e:
            self.last_error=f'{type(e).__name__}: {e}'
            # Do not silently present old quotes as fresh.
            for q in self.snapshot.values(): q['stale']=True; q['refresh_error']=self.last_error
            self.stats={**self.stats,'last_error':self.last_error,'as_of':self.last_snapshot_at}
        return self.status()

    def status(self):
        top=sorted(self.snapshot.values(),key=lambda q:q.get('up_pct',-999),reverse=True)[:100]
        return {'radar':dict(self.stats),'last_error':self.last_error,'last_snapshot_at':self.last_snapshot_at,
            'dynamic_candidates':self.candidates[:50], 'market_snapshot':top}
