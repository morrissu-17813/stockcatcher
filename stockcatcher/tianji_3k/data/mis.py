from __future__ import annotations
from datetime import datetime, timezone, timedelta
import time
try:
    from curl_cffi import requests as curl_requests
except ImportError:
    import requests as curl_requests
from .config import MIS_BATCH_SIZE, HTTP_TIMEOUT
TAIPEI=timezone(timedelta(hours=8))
class MISProvider:
    def __init__(self, stock_info_map=None, exchange_resolver=None):
        self.stock_info_map=stock_info_map or {}; self.exchange_resolver=exchange_resolver or (lambda s:'tse'); self.session=curl_requests.Session(); self.initialized=False
    def _ensure(self):
        if self.initialized:return
        try:self.session.get('https://mis.twse.com.tw/stock/index.jsp',impersonate='chrome120',timeout=6)
        except Exception:pass
        self.initialized=True
    @staticmethod
    def _num(v):
        try:
            s=str(v).replace(',','').strip(); return 0.0 if s in {'','-','--','null','None'} else float(s)
        except (TypeError,ValueError): return 0.0
    def fetch_batch(self):
        self._ensure(); symbols=list(self.stock_info_map); out={}
        for i in range(0,len(symbols),MIS_BATCH_SIZE):
            batch=symbols[i:i+MIS_BATCH_SIZE]; ex='|'.join(f'{self.exchange_resolver(s)}_{s}.tw' for s in batch)
            try:
                r=self.session.get('https://mis.twse.com.tw/stock/api/getStockInfo.jsp',params={'ex_ch':ex,'_':int(time.time()*1000)},impersonate='chrome120',timeout=HTTP_TIMEOUT); payload=r.json()
                for item in payload.get('msgArray',[]):
                    sid=str(item.get('c','')).strip(); y=self._num(item.get('y')); z=self._num(item.get('z')); lp=z if z>0 else y
                    if not sid or lp<=0: continue
                    # TWSE/TPEx MIS `v` is cumulative volume in LOTS.
                    # Keep explicit units so downstream code cannot silently
                    # divide the value by 1000 a second time.
                    v_lots=float(self._num(str(item.get('v','0')).replace(',','')))
                    up=(lp/y-1)*100 if y>0 else 0.0
                    identity='|'.join([sid,str(item.get('t','')),str(item.get('tv','')),str(item.get('z','')),str(item.get('v','')),str(item.get('d',''))])
                    out[sid]={'symbol':sid,'current_price':lp,'previous_close':y,'today_open':self._num(item.get('o',y)),
                              'cumulative_volume':v_lots, 'cumulative_volume_lots':v_lots,
                              'cumulative_volume_shares':v_lots*1000.0,
                              'up_pct':round(up,4),'is_traded':str(item.get('z','-')) not in {'-','0'},
                              'data_identity':identity,'observed_at':datetime.now(TAIPEI)}
            except Exception: continue
        return out
