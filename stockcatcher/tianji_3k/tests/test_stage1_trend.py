from tianji_3k.stage1.trend_engine import evaluate

def bars(closes): return [{'date':f'2026-01-{i+1:02d}','close':x} for i,x in enumerate(closes)]

def test_pass():
    # Strong rising series: latest close above both MAs and MA20 rising.
    r=evaluate({'symbol':'1234','name':'X'},bars([50+i for i in range(70)]))
    assert r.status=='PASS'

def test_fail_close_ma20():
    xs=[50+i for i in range(60)]+[1]
    r=evaluate({'symbol':'1234'},bars(xs))
    assert r.status=='FAIL'
    assert r.first_failure=='CLOSE_LE_MA20'

def test_unknown_history():
    r=evaluate({'symbol':'1234'},bars([10+i for i in range(60)]))
    assert r.status=='UNKNOWN'
    assert r.first_failure=='TREND_HISTORY_INSUFFICIENT'

def test_ma20_slope():
    # MA20 at K0 falls while close remains above both averages.
    xs=[50]*40+[110]*20+[109]*19+[109.5]
    r=evaluate({'symbol':'1234'},bars(xs))
    assert r.status=='FAIL'
    assert r.first_failure=='MA20_SLOPE_NOT_UP'
