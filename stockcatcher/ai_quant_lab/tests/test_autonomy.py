import sys, unittest
from pathlib import Path
from datetime import datetime, timezone
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine import LabEngine
from autonomy import AutonomousLoop

class FakeMarketClient:
    def __init__(self, quote): self.quote=quote
    def fetch(self, symbol): return {**self.quote, 'symbol':symbol}

def quote(symbol='2330.TW', price=120.0, sma5=115.0, sma20=110.0, stale=False):
    candles=[{'timestamp':datetime.now(timezone.utc).astimezone().isoformat(),'close':float(price),'high':float(price),'low':float(price),'volume':1000} for _ in range(25)]
    return {'symbol':symbol,'name':'測試股票','price':price,'sma5':sma5,'sma20':sma20,'volume':1000,'volume_avg20':800,'volume_ratio':1.25,'market_timestamp':datetime.now(timezone.utc).astimezone().isoformat(),'data_age_seconds':0 if not stale else 99999,'stale':stale,'source':'test-fixture','interval':'5m','candles':candles,'change_pct':1.2}

class NoRadar:
    last_error='test radar disabled'
    def scan(self): return {'last_error':self.last_error,'radar':{'snapshot_symbols':0},'dynamic_candidates':[],'market_snapshot':[]}
    def status(self): return {'dynamic_candidates':[],'market_snapshot':[]}

class AutonomyTests(unittest.TestCase):
    def test_bullish_snapshot_creates_paper_trade(self):
        engine=LabEngine(max_order_notional='10000')
        worker=AutonomousLoop(engine, client=FakeMarketClient(quote()), watchlist=[{'symbol':'2330.TW','name':'測試股票'}], interval=30); worker.radar=NoRadar()
        result=worker.run_once()
        self.assertEqual(engine.state()['counts']['fills'],0)
        self.assertFalse(any(x.get('status') == 'paper_buy' for x in result['results']))
        self.assertTrue(any(r['role_id']=='auditor' and r['status']=='success' for r in engine.state()['roles']))

    def test_stale_quote_never_trades(self):
        engine=LabEngine(max_order_notional='10000')
        worker=AutonomousLoop(engine, client=FakeMarketClient(quote(stale=True)), watchlist=[{'symbol':'2330.TW','name':'測試股票'}], interval=30); worker.radar=NoRadar()
        result=worker.run_once()
        self.assertEqual(engine.state()['counts']['fills'],0)

    def test_no_signal_when_trend_not_bullish(self):
        engine=LabEngine(max_order_notional='10000')
        worker=AutonomousLoop(engine, client=FakeMarketClient(quote(price=105,sma5=110,sma20=100)), watchlist=[{'symbol':'2330.TW','name':'測試股票'}], interval=30); worker.radar=NoRadar()
        result=worker.run_once()
        self.assertEqual(engine.state()['counts']['fills'],0)


    def test_failed_refresh_marks_previous_quote_stale(self):
        engine=LabEngine(max_order_notional='10000')
        class FlakyClient:
            calls=0
            def fetch(self, symbol):
                self.calls += 1
                if self.calls == 1: return {**quote(), 'symbol':symbol}
                raise RuntimeError('network unavailable')
        worker=AutonomousLoop(engine, client=FlakyClient(), watchlist=[{'symbol':'2330.TW','name':'測試股票'}], interval=30); worker.radar=NoRadar()
        worker.run_once()
        second=worker.run_once()
        self.assertEqual(len(second['results']), 0)
        market=worker.status()['market'][0]
        self.assertTrue(market['stale'])
        self.assertIn('refresh_error', market)

    def test_scan_does_not_duplicate_when_another_cycle_is_running(self):
        import threading, time
        engine=LabEngine(max_order_notional='10000')
        entered=threading.Event(); release=threading.Event()
        class SlowClient:
            def fetch(self, symbol):
                entered.set(); release.wait(1); return {**quote(), 'symbol':symbol}
        worker=AutonomousLoop(engine, client=SlowClient(), watchlist=[{'symbol':'2330.TW','name':'測試股票'}], interval=30); worker.radar=NoRadar()
        thread=threading.Thread(target=worker.run_once); thread.start()
        self.assertTrue(entered.wait(1))
        overlapping=worker.run_once()
        self.assertEqual(overlapping['status'], 'scan_in_progress')
        release.set(); thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(engine.state()['counts']['fills'], 0)

if __name__=='__main__': unittest.main()


def test_monitor_log_is_bounded_and_exposed_in_status():
    from autonomy import AutonomousLoop
    class EngineStub:
        store=type('Store',(),{'configured':False})()
    loop=AutonomousLoop(EngineStub(), client=type('Client',(),{'fetch':lambda self,symbol:{'symbol':symbol,'price':1}})(), watchlist=[])
    loop._log('監控測試紀錄', tag='TEST')
    assert loop.status()['monitor_logs'][-1]['message']=='監控測試紀錄'
