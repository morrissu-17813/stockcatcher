from __future__ import annotations
import argparse,json,csv
from pathlib import Path

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--stage3-json',default='tianji_3k/cache/stage3_volume.json');ap.add_argument('--stage2-json',default='tianji_3k/cache/stage2_breakout.json');ap.add_argument('--output',default='tianji_3k/cache/final_3k_pool.json');a=ap.parse_args()
 s2={str(x['symbol']):x for x in json.loads(Path(a.stage2_json).read_text(encoding='utf-8'))}; s3=json.loads(Path(a.stage3_json).read_text(encoding='utf-8')); final=[]
 for r in s3:
  if r.get('pass') is True:
   x=dict(s2.get(str(r['symbol']),{}));x['stage3']=r;x['three_k_pass']=True;final.append(x)
 Path(a.output).write_text(json.dumps(final,ensure_ascii=False,indent=2),encoding='utf-8')
 csvp=Path(a.output).with_suffix('.csv');
 keys=['symbol','date','close','high','k1_high','k2_high','gain_pct','breakout_level','latest_date','volume_lots','yesterday_volume_lots','vma5_lots','volume_ratio','three_k_pass']
 with open(csvp,'w',newline='',encoding='utf-8-sig') as f:
  w=csv.DictWriter(f,fieldnames=keys);w.writeheader()
  for x in final:
   r=x.get('stage3',{});w.writerow({k:(x.get(k) if k in x else r.get(k)) for k in keys})
 print('='*72);print('天機 3K — FINAL STOCK POOL');print('='*72);print('3K PASS :',len(final));
 for x in final: print(' ',x['symbol'],x.get('close'),x.get('gain_pct'),x.get('breakout_level'),x.get('stage3',{}).get('volume_ratio'))
 print('JSON written:',Path(a.output).resolve());print('CSV written :',csvp.resolve())
if __name__=='__main__':main()
