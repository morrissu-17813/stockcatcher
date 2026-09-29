from pathlib import Path
import tempfile
import pandas as pd
from tianji_3k.data.cache_first import CacheFirstDailyProvider

class RecorderFallback:
    def __init__(self): self.calls=[]
    def get_daily(self, symbol, start, end):
        self.calls.append((symbol,start,end)); d=pd.bdate_range(start,end)
        return pd.DataFrame({"date":d,"stock_id":[symbol]*len(d),"open":100.0,"max":101.0,"min":99.0,"close":100.5,"Trading_Volume":1000000,"Trading_money":100000000,"spread":0.5,"Trading_turnover":1000})

def write_cache(path,start,end,symbol="6409"):
    d=pd.bdate_range(start,end)
    df=pd.DataFrame({"date":d,"stock_id":[symbol]*len(d),"open":100.0,"max":101.0,"min":99.0,"close":100.5,"Trading_Volume":1000000,"Trading_money":100000000,"spread":0.5,"Trading_turnover":1000})
    path.write_text(df.to_json(orient="records",date_format="iso"),encoding="utf-8")

def test_weekend_tail_only_fetches_monday():
    with tempfile.TemporaryDirectory() as td:
        p=Path(td); write_cache(p/"TaiwanStockPrice_6409_2026-03-25_2026-09-18.json","2026-03-25","2026-09-18")
        x=CacheFirstDailyProvider("NO_NETWORK",cache_dir=p); f=RecorderFallback(); x.fallback=f
        r=x.get_daily("6409","2026-03-25","2026-09-21")
        assert f.calls==[("6409","2026-09-21","2026-09-21")]
        assert x.stats()["finmind_fallbacks"]==1
        assert len(r)==len(pd.bdate_range("2026-03-25","2026-09-21"))

def test_full_cache_no_fetch():
    with tempfile.TemporaryDirectory() as td:
        p=Path(td); write_cache(p/"TaiwanStockPrice_6409_2026-03-25_2026-09-21.json","2026-03-25","2026-09-21")
        x=CacheFirstDailyProvider("NO_NETWORK",cache_dir=p); f=RecorderFallback(); x.fallback=f
        r=x.get_daily("6409","2026-03-25","2026-09-21")
        assert f.calls==[] and x.stats()["cache_hits"]==1 and len(r)==len(pd.bdate_range("2026-03-25","2026-09-21"))

def test_internal_gap():
    with tempfile.TemporaryDirectory() as td:
        p=Path(td); write_cache(p/"TaiwanStockPrice_6409_a.json","2026-09-14","2026-09-15"); write_cache(p/"TaiwanStockPrice_6409_b.json","2026-09-17","2026-09-18")
        x=CacheFirstDailyProvider("NO_NETWORK",cache_dir=p); f=RecorderFallback(); x.fallback=f
        r=x.get_daily("6409","2026-09-14","2026-09-18")
        assert f.calls==[("6409","2026-09-16","2026-09-16")] and len(r)==len(pd.bdate_range("2026-09-14","2026-09-18"))

def test_union_avoids_fetch():
    with tempfile.TemporaryDirectory() as td:
        p=Path(td); write_cache(p/"TaiwanStockPrice_6409_old.json","2026-09-14","2026-09-16"); write_cache(p/"TaiwanStockPrice_6409_new.json","2026-09-17","2026-09-21")
        x=CacheFirstDailyProvider("NO_NETWORK",cache_dir=p); f=RecorderFallback(); x.fallback=f
        r=x.get_daily("6409","2026-09-14","2026-09-21")
        assert f.calls==[] and x.stats()["cache_hits"]==1 and len(r)==len(pd.bdate_range("2026-09-14","2026-09-21"))
