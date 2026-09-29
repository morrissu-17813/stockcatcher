from __future__ import annotations
import argparse,json,csv
from pathlib import Path
from collections import Counter

def n(v):
 try: x=float(v); return x if x==x else None
 except: return None

def cache_rows(cache_dir):
 by={}
 for p in Path(cache_dir).glob('*.json'):
  try:d=json.loads(p.read_text(encoding='utf-8'))
  except:continue
  if isinstance(d,dict):d=[d]
  for r in d if isinstance(d,list) else []:
   sid=str(r.get('stock_id') or r.get('symbol') or '').strip(); date=str(r.get('date') or '')
   if len(sid)!=4 or not date: continue
   vol=n(r.get('Trading_Volume',r.get('volume')))
   if vol is None: continue
   by.setdefault(sid,{})[date]=vol
 return by

def eval_volume(rows):
 dates=sorted(rows)
 if len(dates)<6:return {'pass':False,'first_fail':'INSUFFICIENT_VOLUME_HISTORY','unknown':True}
 vals=[rows[d]/1000 for d in dates[-6:]]
 today,yesterday=vals[-1],vals[-2]
 vma5=sum(vals[-6:-1])/5
 checks={'vma5_ge_1000':vma5>=1000,'today_gt_yesterday':today>yesterday,'volume_ratio_ge_1_5':today/vma5>=1.5 if vma5>0 else False}
 reason=next((k for k,v in checks.items() if not v),'')
 return {'pass':not reason,'unknown':False,'latest_date':dates[-1],'volume_lots':today,'yesterday_volume_lots':yesterday,'vma5_lots':vma5,'volume_ratio':today/vma5 if vma5 else None,'checks':checks,'first_fail':reason}

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--stage2-json',default='tianji_3k/cache/stage2_breakout.json');ap.add_argument('--cache-dir',default='tianji_3k/cache/daily');ap.add_argument('--csv',default='tianji_3k/cache/stage3_volume.csv');ap.add_argument('--json',default='tianji_3k/cache/stage3_volume.json');a=ap.parse_args()
 s=json.loads(Path(a.stage2_json).read_text(encoding='utf-8')); symbols=[str(x['symbol']) for x in s if x.get('pass') is True]; c=cache_rows(a.cache_dir); out=[]
 for sid in symbols: out.append({'symbol':sid,**eval_volume(c.get(sid,{}))})
 Path(a.json).write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8'); keys=sorted({k for r in out for k in r})
 with open(a.csv,'w',newline='',encoding='utf-8-sig') as f: w=csv.DictWriter(f,fieldnames=keys);w.writeheader();w.writerows(out)
 print('='*72);print('天機 3K — Stage 3 Volume Engine');print('='*72);print('Stage 2 PASS input :',len(symbols));print('PASS               :',sum(r.get('pass') is True for r in out));print('FAIL/UNKNOWN       :',sum(r.get('pass') is not True for r in out));print('First fail:');[print(f'  {k:28s} {v}') for k,v in Counter(r.get('first_fail','') for r in out if r.get('pass') is not True).most_common()];print('CSV written:',Path(a.csv).resolve());print('JSON written:',Path(a.json).resolve())
if __name__=='__main__':main()
