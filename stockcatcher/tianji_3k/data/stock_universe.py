from __future__ import annotations
import re
from typing import Any, Dict, List
import requests

class StockUniverseProvider:
    def __init__(self, timeout: int = 15): self.timeout = timeout
    def _get(self, url: str):
        r=requests.get(url, timeout=self.timeout); r.raise_for_status(); return r.json()
    @staticmethod
    def _lots(v):
        try: return float(str(v).replace(',',''))/1000.0
        except (TypeError,ValueError): return 0.0
    def fetch_listed(self):
        rows=self._get('https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL')
        out=[]
        for x in rows if isinstance(rows,list) else []:
            sid=str(x.get('Code','')).strip()
            if re.fullmatch(r'\d{4}',sid):
                out.append({'symbol':sid,'name':str(x.get('Name','')).strip(),'market':'TWSE','exchange':'tse','security_type':'common_stock','previous_volume_lots':self._lots(x.get('TradeVolume'))})
        return out
    def fetch_otc(self):
        rows=self._get('https://www.tpex.org.tw/openapi/v1/tpex_mainboard_quotes')
        out=[]
        for x in rows if isinstance(rows,list) else []:
            sid=str(x.get('SecuritiesCompanyCode','')).strip()
            if re.fullmatch(r'\d{4}',sid):
                out.append({'symbol':sid,'name':str(x.get('CompanyName',x.get('SecuritiesCompanyName',''))).strip(),'market':'TPEx','exchange':'otc','security_type':'common_stock','previous_volume_lots':self._lots(x.get('TradingShares'))})
        return out
    def fetch(self):
        rows=[]
        for fn in (self.fetch_listed,self.fetch_otc):
            try: rows.extend(fn())
            except Exception: pass
        merged={}
        for x in rows: merged[x['symbol']]=x
        return list(merged.values())
