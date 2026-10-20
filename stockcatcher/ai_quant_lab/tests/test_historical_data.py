import json, os
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch
import historical_data


def make_bars(count=70):
    today=date.today()
    rows=[]
    for i in range(count,0,-1):
        d=today-timedelta(days=i)
        if d.weekday()>=5: continue
        px=100+i/10
        rows.append({'date':d.isoformat(),'open':px-1,'max':px+1,'min':px-2,'close':px,'Trading_Volume':1000000})
    return rows

def test_cache_first_does_not_call_api_when_enough_bars(tmp_path):
    folder=tmp_path/'daily'; folder.mkdir()
    (folder/'TaiwanStockPrice_2330_2026-01-01_2026-12-31.json').write_text(json.dumps(make_bars(120)),encoding='utf-8')
    with patch.object(historical_data,'_CACHE_DIR',folder), patch.object(historical_data,'_CACHE',{}), patch.object(historical_data,'_fetch_api',side_effect=AssertionError('API should not be called')):
        result=historical_data.get_history('2330')
    assert result['bars'] >= 60
    assert result['source']=='tianji_3k/cache/daily'
    assert result['candles'][-1]['date'] < date.today().isoformat()

def test_api_fallback_merges_with_cache_when_cache_short(tmp_path):
    folder=tmp_path/'daily'; folder.mkdir()
    short=make_bars(20)
    (folder/'TaiwanStockPrice_2454_2026-01-01_2026-12-31.json').write_text(json.dumps(short),encoding='utf-8')
    fetched=make_bars(120)
    with patch.object(historical_data,'_CACHE_DIR',folder), patch.object(historical_data,'_CACHE',{}), patch.object(historical_data,'_fetch_api',return_value=fetched), patch.dict(os.environ, {'FINMIND_TOKEN':'test-token'}):
        result=historical_data.get_history('2454')
    assert result['bars'] >= 60
    assert result['source']=='cache + FinMind API'
