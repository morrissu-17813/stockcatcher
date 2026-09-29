from __future__ import annotations
import requests
from .gate import evaluate_intraday_notification
from ..data.config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
class TelegramNotifier:
    def __init__(self,token=None,chat_id=None): self.token=token or TELEGRAM_BOT_TOKEN; self.chat_id=chat_id or TELEGRAM_CHAT_ID
    @property
    def enabled(self): return bool(self.token and self.chat_id)
    def send(self,text):
        if not self.enabled: return {'sent':False,'status':'DISABLED','message_id':None}
        url=f'https://api.telegram.org/bot{self.token}/sendMessage'
        r=requests.post(url,json={'chat_id':self.chat_id,'text':text},timeout=10); r.raise_for_status(); p=r.json(); return {'sent':bool(p.get('ok')),'status':'SENT' if p.get('ok') else 'FAILED','message_id':(p.get('result') or {}).get('message_id')}
    def send_premarket_watchlist(self,trade_date,pool):
        lines=[f'🌅 PREMARKET_WATCHLIST | {trade_date}', '盤前觀察池（非盤中訊號）', f'共 {len(pool)} 檔，盤中 Radar 將持續觀察：']
        for x in pool: lines.append(f"• {x.get('symbol')} {x.get('name','')} | Close {x.get('close','-')} | Breakout {x.get('breakout_level','-')}")
        return self.send('\n'.join(lines))
    def send_intraday_prediction(self,event):
        s=event['trigger_snapshot']; v=event.get('volume_snapshot',{}); c=event['context']
        text=(f"🔥 INTRADAY_3K_PREDICTION | {event['trade_date']}\n{c['symbol']} {c.get('name','')}\n"
              f"現價 {s.get('current_price',0):.2f} | 漲幅 {s.get('up_pct',0):.2f}%\n"
              f"突破基準 {s.get('breakout_level',0):.2f} | 有效突破 {s.get('effective_breakout')}\n"
              f"預估量 {v.get('projected_volume_lots',0):.0f} 張 | 預估量比 {v.get('projected_ratio','-')}\n"
              f"注意：此訊號為盤中預判，收盤後以 GROUND_TRUTH 驗證。")
        return self.send(text)
    def send_ground_truth(self,gt):
        status='PASS' if gt.get('ground_truth_3k') else 'FAIL'
        return self.send(f"🏁 GROUND_TRUTH | {gt.get('trade_date')} | {gt.get('symbol')}\n收盤驗證：{status}\n收盤 {gt.get('close','-')} | 漲幅 {gt.get('gain_pct','-')}%")

def send_telegram(text,chat_id=None,token=None): return TelegramNotifier(token or TELEGRAM_BOT_TOKEN,chat_id or TELEGRAM_CHAT_ID).send(text).get('sent',False)
