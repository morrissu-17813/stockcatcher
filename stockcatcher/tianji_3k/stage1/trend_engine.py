"""天機 3K Stage 1 Trend Engine.

Stage 1 is deliberately limited to the approved four conditions:
1. Close(K0) > MA20(K0)
2. Close(K0) > MA60(K0)
3. MA20(K0) > MA60(K0)
4. MA20(K0) > MA20(K1)

K0 is the latest completed daily bar available in the local cache. No future
bar is used. Missing/insufficient history is UNKNOWN, never PASS.
"""
from __future__ import annotations
import argparse, csv, json, re
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from tianji_3k.data.trading_calendar import TaiwanTradingCalendar
from tianji_3k.data.data_integrity import validate_required_history, validate_ohlc_frame

SYMBOL_RE=re.compile(r'^\d{4}$')

def norm(v: Any)->str: return str(v).strip() if v is not None else ''
def num(v: Any)->Optional[float]:
    if v is None or v=='': return None
    try: return float(str(v).replace(',','').strip())
    except (TypeError,ValueError): return None

def date_key(v: Any)->Optional[str]:
    s=norm(v).replace('/','-')
    if not s:return None
    for f in ('%Y-%m-%d','%Y%m%d','%Y-%m-%d %H:%M:%S'):
        try:return datetime.strptime(s,f).date().isoformat()
        except ValueError:pass
    try:return datetime.fromisoformat(s).date().isoformat()
    except ValueError:return None

def extract_rows(payload: Any)->List[Dict[str,Any]]:
    if isinstance(payload,list): return [x for x in payload if isinstance(x,dict)]
    if isinstance(payload,dict):
        for k in ('data','rows','result','results'):
            if isinstance(payload.get(k),list): return [x for x in payload[k] if isinstance(x,dict)]
    return []

def row_symbol(r): return norm(r.get('stock_id') or r.get('symbol') or r.get('Code') or r.get('Symbol'))
def row_date(r): return date_key(r.get('date') or r.get('Date') or r.get('trade_date') or r.get('TradingDate'))
def close_value(r):
    for k in ('close','Close','收盤價','closing_price'):
        v=num(r.get(k))
        if v is not None:return v
    return None

def open_value(r):
    for k in ('open','Open','開盤價'):
        v=num(r.get(k))
        if v is not None:return v
    return None

def high_value(r):
    for k in ('max','high','High','最高價'):
        v=num(r.get(k))
        if v is not None:return v
    return None

def load_daily_cache(cache_dir: Path)->Dict[str,List[Dict[str,Any]]]:
    out:Dict[str,Dict[str,Dict[str,Any]]]={}
    if not cache_dir.exists():return {}
    for path in sorted(cache_dir.glob('*.json')):
        try: payload=json.loads(path.read_text(encoding='utf-8-sig'))
        except Exception: continue
        for r in extract_rows(payload):
            sid=row_symbol(r); d=row_date(r)
            if not SYMBOL_RE.fullmatch(sid) or not d: continue
            c=close_value(r)
            if c is None: continue
            out.setdefault(sid,{})[d]=r
    return {s:[v for _,v in sorted(ds.items())] for s,ds in out.items()}

def load_stage0(path:Path)->List[Dict[str,Any]]:
    payload=json.loads(path.read_text(encoding='utf-8-sig'))
    if isinstance(payload,list): rows=payload
    elif isinstance(payload,dict): rows=payload.get('rows',payload.get('data',[]))
    else: rows=[]
    return [r for r in rows if isinstance(r,dict) and bool(r.get('final_stage0_pass'))]

@dataclass
class TrendResult:
    symbol:str
    name:str=''
    stage0_pass:bool=True
    latest_date:str=''
    close:Optional[float]=None
    ma20:Optional[float]=None
    ma60:Optional[float]=None
    ma20_prev:Optional[float]=None
    close_gt_ma20:Optional[bool]=None
    close_gt_ma60:Optional[bool]=None
    ma20_gt_ma60:Optional[bool]=None
    ma20_slope_up:Optional[bool]=None
    history_bars:int=0
    status:str='UNKNOWN'
    first_failure:str=''
    detail:str=''

    @property
    def stage1_pass(self): return self.status=='PASS'

def evaluate(symbol_row:Dict[str,Any], bars:List[Dict[str,Any]], calendar:TaiwanTradingCalendar|None=None)->TrendResult:
    sid=norm(symbol_row.get('symbol') or symbol_row.get('stock_id') or symbol_row.get('Code'))
    r=TrendResult(sid,norm(symbol_row.get('name') or symbol_row.get('Name')))
    # Bars are sorted and already de-duplicated by date.
    r.history_bars=len(bars)
    if len(bars)<61:
        r.status='UNKNOWN'; r.first_failure='TREND_HISTORY_INSUFFICIENT'; r.detail=f'需要至少61根有效日K，實際 {len(bars)}'; return r
    if calendar is not None:
        integrity = validate_required_history(bars, calendar, row_date(bars[-1]) or '', 61)
        if not integrity.ok:
            r.status='UNKNOWN'; r.first_failure=integrity.reason; r.detail=','.join(integrity.missing_dates); return r
    closes=[close_value(x) for x in bars]
    if any(x is None for x in closes):
        r.status='UNKNOWN'; r.first_failure='TREND_DATA_INVALID'; r.detail='日K存在無效收盤價'; return r
    k0=bars[-1]; r.latest_date=row_date(k0) or ''
    r.close=closes[-1]
    r.ma20=sum(closes[-20:])/20
    r.ma60=sum(closes[-60:])/60
    # MA20(K1) = previous completed bar's 20-day moving average, using closes through K1.
    r.ma20_prev=sum(closes[-21:-1])/20
    r.close_gt_ma20=r.close>r.ma20
    r.close_gt_ma60=r.close>r.ma60
    r.ma20_gt_ma60=r.ma20>r.ma60
    r.ma20_slope_up=r.ma20>r.ma20_prev
    checks=[('CLOSE_LE_MA20',r.close_gt_ma20),('CLOSE_LE_MA60',r.close_gt_ma60),('MA20_LE_MA60',r.ma20_gt_ma60),('MA20_SLOPE_NOT_UP',r.ma20_slope_up)]
    for reason,ok in checks:
        if not ok:
            r.status='FAIL'; r.first_failure=reason; r.detail='; '.join(f'{a}={b}' for a,b in [('Close',r.close),('MA20',r.ma20),('MA60',r.ma60),('MA20_prev',r.ma20_prev)])
            return r
    r.status='PASS'; r.detail='Stage 1 四條件全部通過'; return r

def write_results(results:List[TrendResult], csv_path:Optional[Path], json_path:Optional[Path]):
    rows=[asdict(x) for x in results]
    if csv_path:
        csv_path.parent.mkdir(parents=True,exist_ok=True)
        with csv_path.open('w',newline='',encoding='utf-8-sig') as f:
            w=csv.DictWriter(f,fieldnames=list(rows[0].keys()) if rows else list(asdict(TrendResult('')).keys())); w.writeheader(); w.writerows(rows)
    if json_path:
        json_path.parent.mkdir(parents=True,exist_ok=True); json_path.write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')

def main(argv=None):
    ap=argparse.ArgumentParser(description='天機 3K Stage 1 Trend Engine')
    ap.add_argument('--stage0-json',required=True)
    ap.add_argument('--cache-dir',required=True)
    ap.add_argument('--csv',required=True)
    ap.add_argument('--json',required=True)
    args=ap.parse_args(argv)
    stage0=load_stage0(Path(args.stage0_json)); cache=load_daily_cache(Path(args.cache_dir))
    calendar=TaiwanTradingCalendar(); calendar.ensure()
    results=[]
    for row in stage0:
        sid=row_symbol(row); results.append(evaluate(row,cache.get(sid,[]),calendar))
    results.sort(key=lambda x:x.symbol)
    from collections import Counter
    c=Counter(r.status for r in results)
    print('='*72); print('天機 3K — Stage 1 Trend Engine'); print('='*72)
    print(f'Stage 0 PASS input       : {len(stage0):,}')
    print(f'Daily cache symbols      : {len(cache):,}')
    print(f'PASS                     : {c["PASS"]:,}')
    print(f'FAIL                     : {c["FAIL"]:,}')
    print(f'UNKNOWN                  : {c["UNKNOWN"]:,}')
    print('-'*72); print('第一個未通過/未驗證原因')
    for k,v in Counter(r.first_failure for r in results).most_common(): print(f'  {k:<30} {v:>6,}')
    print('-'*72); print('Stage 1 PASS 條件：Close > MA20、Close > MA60、MA20 > MA60、MA20(K0) > MA20(K1)')
    print('-'*72); print('Stage 1 PASS 股票')
    for r in results:
        if r.stage1_pass: print(f'  {r.symbol} {r.name:<12} Close={r.close:.2f} MA20={r.ma20:.2f} MA60={r.ma60:.2f} slope={r.ma20_prev:.2f}->{r.ma20:.2f} [{r.latest_date}]')
    write_results(results,Path(args.csv),Path(args.json)); print(f'CSV written             : {Path(args.csv).resolve()}'); print(f'JSON written            : {Path(args.json).resolve()}')
    return 0
if __name__=='__main__': raise SystemExit(main())
