import sys, unittest
from pathlib import Path
from datetime import datetime, timedelta
from decimal import Decimal
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine import LabEngine
from autonomy import AutonomousLoop

class FakeStore:
    configured=True
    def __init__(self): self.rows=[]
    def list_rows(self,*a,**k): return []
    def insert(self,table,row): self.rows.append((table,row)); return {'persisted':True}
    def record_event(self,event,outcome): self.rows.append(('ai_quant_lab_events',{'event':event,'outcome':outcome})); return {'persisted':True}
    def record_trade(self,event,fill): self.rows.append(('ai_quant_lab_paper_trades',{'event':event,'fill':fill})); return {'persisted':True}
    def record_report(self,*a): return {'persisted':True}

class FakeRadar:
    def __init__(self): self.i=0; self.last_error=None; self.snapshot={}
    def scan(self):
        self.i+=1; ident=f'mis-{self.i}'
        q={'symbol':'1234','name':'測試股','market':'TWSE','security_type':'common_stock','price':106.0,'current_price':106.0,'previous_close':100.0,'today_open':101.0,'up_pct':6.0,'volume_lots':5000,'cumulative_volume_lots':5000,'observed_at':(datetime.now().astimezone().replace(hour=10,minute=30,second=0,microsecond=0)).isoformat(),'data_age_seconds':1,'stale':False,'data_identity':ident,'source':'fake MIS','is_traded':True}
        self.snapshot={'1234':q}
        return {'last_error':None,'last_snapshot_at':q['observed_at'],'radar':{'snapshot_symbols':1},'dynamic_candidates':[{'symbol':'1234','name':'測試股','market':'TWSE','price':106,'up_pct':6,'volume_lots':5000,'source':'fake MIS'}]}
    def status(self): return {'dynamic_candidates':[]}

class FakeHistory:
    def context(self,symbol): return {'symbol':symbol,'stage1_pass':True,'liquidity_pass':True,'breakout_level':100.0,'vma5_lots':2000.0,'ma20':105,'ma60':100,'ma20_prev':104}

class FakeFugle5m:
    def confirm_micro_breakout(self,symbol,min_volume_ratio=1.2): return {'passed':True,'reason':'FUGLE_5M_CONFIRMED','bar_time':'2026-10-16T10:25:00+08:00','structure_pass':True,'volume_pass':True,'volume_ratio':1.5,'stop_price':103.0}

class FakeDisplayClient:
    def fetch(self,symbol): raise RuntimeError('display provider offline')

class ConfirmationChainTests(unittest.TestCase):
    def test_two_distinct_mis_snapshots_then_5m_and_projected_volume_required(self):
        store=FakeStore(); engine=LabEngine(max_order_notional='100000',store=store)
        loop=AutonomousLoop(engine,client=FakeDisplayClient(),watchlist=[],interval=30)
        loop.radar=FakeRadar(); loop.history_provider=FakeHistory(); loop.fugle_5m=FakeFugle5m()
        first=loop.run_once()
        self.assertEqual(first['results'][0]['status'],'breakout_pending')
        self.assertEqual(engine.state()['counts']['fills'],0)
        second=loop.run_once()
        self.assertEqual(second['results'][0]['status'],'paper_buy')
        self.assertEqual(engine.state()['counts']['fills'],1)
        self.assertTrue(any(t=='ai_quant_lab_paper_trades' for t,_ in store.rows))
        self.assertTrue(any(t=='ai_quant_lab_events' for t,_ in store.rows))

    def test_missing_supabase_blocks_paper_fill_even_if_confirmation_passes(self):
        engine=LabEngine(max_order_notional='100000')
        loop=AutonomousLoop(engine,client=FakeDisplayClient(),watchlist=[],interval=30)
        loop.radar=FakeRadar(); loop.history_provider=FakeHistory(); loop.fugle_5m=FakeFugle5m()
        loop.run_once(); second=loop.run_once()
        self.assertEqual(second['results'][0]['status'],'persistence_blocked')
        self.assertEqual(engine.state()['counts']['fills'],0)

    def test_missing_fugle_confirmation_never_trades(self):
        store=FakeStore(); engine=LabEngine(max_order_notional='100000',store=store)
        class FailFugle:
            def confirm_micro_breakout(self,*a,**k): return {'passed':False,'reason':'FUGLE_5M_INSUFFICIENT_COMPLETED_BARS'}
        loop=AutonomousLoop(engine,client=FakeDisplayClient(),watchlist=[],interval=30)
        loop.radar=FakeRadar(); loop.history_provider=FakeHistory(); loop.fugle_5m=FailFugle()
        loop.run_once(); second=loop.run_once()
        self.assertEqual(second['results'][0]['status'],'fugle_5m_waiting')
        self.assertEqual(engine.state()['counts']['fills'],0)

if __name__=='__main__': unittest.main()
