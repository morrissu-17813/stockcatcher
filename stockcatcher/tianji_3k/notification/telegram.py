from __future__ import annotations
import html
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
        r=requests.post(url,json={'chat_id':self.chat_id,'text':text,'parse_mode':'HTML','disable_web_page_preview':True},timeout=10); r.raise_for_status(); p=r.json(); return {'sent':bool(p.get('ok')),'status':'SENT' if p.get('ok') else 'FAILED','message_id':(p.get('result') or {}).get('message_id')}
    def send_premarket_watchlist(self,trade_date,pool):
        lines=[f'🌅 PREMARKET_WATCHLIST | {trade_date}', '盤前觀察池（非盤中訊號）', f'共 {len(pool)} 檔，盤中 Radar 將持續觀察：']
        for x in pool: lines.append(f"• {x.get('symbol')} {x.get('name','')} | Close {x.get('close','-')} | Breakout {x.get('breakout_level','-')}")
        return self.send('\n'.join(lines))
    def send_intraday_prediction(self,event):
        s=event['trigger_snapshot']; v=event.get('volume_snapshot',{}); c=event['context']
        symbol = str(c.get('symbol','')).strip()
        name = html.escape(str(c.get('name','')).strip())
        nstock_url = f"https://www.nstock.tw/{symbol}"
        current_price = float(s.get('current_price') or 0)
        up_pct = float(s.get('up_pct') or 0)
        breakout_level = float(s.get('breakout_level') or 0)
        projected_volume = float(v.get('projected_volume_lots') or 0)
        projected_ratio_raw = v.get('projected_ratio')
        try:
            projected_ratio = f"{float(projected_ratio_raw):.1f}x"
        except (TypeError, ValueError):
            projected_ratio = "-"
        effective_breakout = bool(s.get('effective_breakout'))
        signal_level = str(s.get('signal_level') or event.get('signal_level') or 'STRONG').upper()
        title = {'EARLY': '⚡ 天機 3K EARLY', 'STRONG': '🔥 天機 3K STRONG', 'MOMENTUM': '🔥🔥 天機 3K MOMENTUM'}.get(signal_level, '🔥 天機 3K 盤中預判')
        text=(
            f"<b>{title}</b> | {event['trade_date']}\n\n"
            f"🔗 <a href=\"{nstock_url}\"><b>{html.escape(symbol)} {name}</b></a>\n\n"
            f"💰 現價　　{current_price:.1f} 元\n"
            f"📈 漲幅　　{up_pct:+.1f}%\n"
            f"🚀 突破基準 {breakout_level:.1f} 元\n"
            f"{'✅' if effective_breakout else '⚪'} 有效突破　{'是' if effective_breakout else '否'}\n\n"
            f"📊 預估量　　{projected_volume:,.0f} 張\n"
            f"⚡ 預估量比　{projected_ratio}\n\n"
            f"📝 <i>盤中預判訊號，收盤後以 GROUND_TRUTH 驗證。</i>"
        )
        return self.send(text)
    def send_ground_truth(self,gt):
        status='PASS' if gt.get('ground_truth_3k') else 'FAIL'
        return self.send(f"🏁 GROUND_TRUTH | {gt.get('trade_date')} | {gt.get('symbol')}\n收盤驗證：{status}\n收盤 {gt.get('close','-')} | 漲幅 {gt.get('gain_pct','-')}%")

def send_telegram(text,chat_id=None,token=None): return TelegramNotifier(token or TELEGRAM_BOT_TOKEN,chat_id or TELEGRAM_CHAT_ID).send(text).get('sent',False)
