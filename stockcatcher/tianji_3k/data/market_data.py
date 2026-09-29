from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Optional
import pandas as pd

def normalize_volume_shares(value: Any) -> float:
    try: return max(0.0,float(str(value).replace(',','')))
    except (TypeError,ValueError): return 0.0

def volume_lots(volume_shares: float) -> float: return normalize_volume_shares(volume_shares)/1000.0

def standardize_daily_frame(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty: return pd.DataFrame()
    x=df.copy(); aliases={'max':'high','min':'low','Trading_Volume':'volume','opening_price':'open','closing_price':'close'}
    x=x.rename(columns={k:v for k,v in aliases.items() if k in x.columns})
    required=['open','high','low','close','volume']
    if not all(c in x.columns for c in required): return pd.DataFrame()
    for c in required: x[c]=pd.to_numeric(x[c],errors='coerce')
    if 'date' in x.columns:
        x['date']=pd.to_datetime(x['date'],errors='coerce'); x=x.sort_values('date')
    x=x.dropna(subset=required).drop_duplicates(subset=['date'] if 'date' in x.columns else None).reset_index(drop=True)
    x['volume_lots']=x['volume'].map(volume_lots); x['ma20']=x['close'].rolling(20).mean(); x['ma60']=x['close'].rolling(60).mean(); x['vma5']=x['volume_lots'].rolling(5).mean()
    return x

class FinMindDailyProvider:
    def __init__(self, token=''):
        self.token=token
    def get_daily(self,symbol,start,end):
        from FinMind.data import DataLoader
        dl=DataLoader()
        if self.token:
            dl.login_by_token(self.token)
        df=dl.taiwan_stock_daily(stock_id=str(symbol),start_date=start,end_date=end)
        return standardize_daily_frame(df)

@dataclass
class DailyKData:
    symbol: str
    frame: pd.DataFrame
    @property
    def valid(self): return self.frame is not None and len(self.frame)>=60
