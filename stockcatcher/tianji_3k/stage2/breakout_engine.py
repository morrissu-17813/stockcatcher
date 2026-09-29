from __future__ import annotations
import argparse, json
from pathlib import Path
from typing import Any

from tianji_3k.data.trading_calendar import TaiwanTradingCalendar
from tianji_3k.data.data_integrity import validate_k012


def _num(v):
    try:
        x=float(v)
        return x if x==x else None
    except: return None

def load_cache(cache_dir: Path):
    by={}
    for p in sorted(cache_dir.glob('*.json')):
        try: data=json.loads(p.read_text(encoding='utf-8'))
        except: continue
        if isinstance(data,dict): data=[data]
        for r in data if isinstance(data,list) else []:
            sid=str(r.get('stock_id') or r.get('symbol') or '').strip()
            d=str(r.get('date') or '').strip()
            if len(sid)==4 and d:
                row={'date':d,'open':_num(r.get('open')),'high':_num(r.get('max',r.get('high'))),'low':_num(r.get('min',r.get('low'))),'close':_num(r.get('close')),'volume_shares':_num(r.get('Trading_Volume',r.get('volume')))}
                by.setdefault(sid,{})[d]=row
    return by

def evaluate(rows, calendar=None):
    dates=sorted(rows)
    valid=[rows[d] for d in dates if all(rows[d].get(k) is not None for k in ('open','high','close'))]
    if calendar is not None and dates:
        latest_date = dates[-1]
        integrity = validate_k012(valid, calendar, latest_date)
        if not integrity.ok:
            return None, integrity.reason
    if len(valid)<3: return None,'INSUFFICIENT_DAILY_K'
    k0,k1,k2=valid[-1],valid[-2],valid[-3]
    gain=k0['close']/k1['close']-1 if k1['close'] else None
    checks={
      'bullish': k0['close']>k0['open'],
      'gain_ge_4pct': gain is not None and gain>=0.04,
      'high_gt_k1': k0['high']>k1['high'],
      'high_gt_k2': k0['high']>k2['high'],
      'close_gt_prev_2_highs': k0['close']>max(k1['high'],k2['high']),
    }
    reason=next((k for k,v in checks.items() if not v),'')
    return {'date':dates[-1],'k0_date':str(k0['date'])[:10],'k1_date':str(k1['date'])[:10],'k2_date':str(k2['date'])[:10],'open':k0['open'],'close':k0['close'],'high':k0['high'],'k1_high':k1['high'],'k2_high':k2['high'],'gain_pct':gain*100 if gain is not None else None,'breakout_level':max(k1['high'],k2['high']),'checks':checks,'pass':not reason,'first_fail':reason},None

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--stage1-json',default='tianji_3k/cache/stage1_trend.json'); ap.add_argument('--cache-dir',default='tianji_3k/cache/daily'); ap.add_argument('--csv',default='tianji_3k/cache/stage2_breakout.csv'); ap.add_argument('--json',default='tianji_3k/cache/stage2_breakout.json'); a=ap.parse_args()
    s=json.loads(Path(a.stage1_json).read_text(encoding='utf-8'))
    symbols=[str(x.get('symbol')) for x in s if str(x.get('status','')).upper() in ('PASS','STAGE1_PASS') or x.get('pass') is True]
    cache=load_cache(Path(a.cache_dir)); out=[]
    calendar = TaiwanTradingCalendar()
    calendar.ensure()
    for sid in symbols:
        e,err=evaluate(cache.get(sid,{}), calendar)
        out.append({'symbol':sid, **(e or {'pass':False,'first_fail':err})})
    Path(a.json).write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    import csv
    keys=sorted({k for r in out for k in r})
    with open(a.csv,'w',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=keys); w.writeheader(); w.writerows(out)
    print('='*72); print('天機 3K — Stage 2 Breakout Engine'); print('='*72); print('Stage 1 PASS input :',len(symbols)); print('PASS               :',sum(r.get('pass') is True for r in out)); print('FAIL/UNKNOWN       :',sum(r.get('pass') is not True for r in out));
    from collections import Counter
    print('First fail:'); [print(f'  {k:28s} {v}') for k,v in Counter(r.get('first_fail','') for r in out if r.get('pass') is not True).most_common()]
    print('CSV written:',Path(a.csv).resolve()); print('JSON written:',Path(a.json).resolve())
if __name__=='__main__': main()
