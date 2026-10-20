import sys, unittest
from pathlib import Path
from decimal import Decimal
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))
from engine import LabEngine
from autonomy import AutonomousLoop

class DurableFakeStore:
    configured = True
    def __init__(self, fail_commit=False):
        self.events=[]; self.trades=[]; self.fail_commit=fail_commit
    def list_rows(self, table, **kwargs): return []
    def commit_event(self, event, outcome, fill):
        if self.fail_commit: raise RuntimeError('simulated durable commit outage')
        self.events.append((event, outcome, fill))
        self.trades.append(fill)
        return {'event_seq': len(self.events), 'atomic': True}
    def record_event(self, event, outcome):
        if self.fail_commit: raise RuntimeError('simulated durable commit outage')
        self.events.append((event, outcome, None))
        return {'event_seq': len(self.events)}
    def record_trade(self, event, fill): self.trades.append(fill)

class FakeRadar:
    def __init__(self, quote): self.snapshot={'2330':quote}

def make_quote(price, identity='tick-1', stale=False):
    return {'symbol':'2330','name':'台積電','price':price,'current_price':price,
            'data_identity':identity,'observed_at':'2026-10-18T10:00:00+08:00',
            'market_timestamp':'2026-10-18T10:00:00+08:00','data_age_seconds':1,
            'stale':stale,'is_traded':True,'source':'fake MIS'}

class V29PaperExitE2ETests(unittest.TestCase):
    def setup_loop(self, price, fail_commit=False, stale=False):
        store=DurableFakeStore(fail_commit=fail_commit)
        engine=LabEngine(store=store, initial_cash=Decimal('1000000'))
        engine.ledger.execute('2330','BUY',10,Decimal('100'))
        loop=AutonomousLoop(engine, client=object(), watchlist=[], interval=20)
        loop.radar=FakeRadar(make_quote(price, stale=stale))
        return loop, engine, store

    def test_end_to_end_stop_loss_updates_ledger_and_durable_event(self):
        loop, engine, store=self.setup_loop(97)
        results=[]; loop._monitor_open_positions(results, 'cycle-1')
        self.assertEqual(results[0]['status'],'paper_stop_loss')
        self.assertEqual(engine.ledger.positions['2330'].quantity,0)
        self.assertEqual(engine.ledger.fills[-1].side,'SELL')
        exit_record=next(row for row in store.events if row[0].get('event_type')=='paper.exit_check')
        self.assertEqual(exit_record[1]['status'],'processed')
        self.assertEqual(exit_record[2]['side'],'SELL')
        self.assertEqual(len(store.trades),1)

    def test_end_to_end_take_profit_updates_ledger_and_durable_event(self):
        loop, engine, store=self.setup_loop(105)
        results=[]; loop._monitor_open_positions(results, 'cycle-1')
        self.assertEqual(results[0]['status'],'paper_take_profit')
        self.assertEqual(engine.ledger.positions['2330'].quantity,0)
        exit_record=next(row for row in store.events if row[0].get('event_type')=='paper.exit_check')
        self.assertEqual(exit_record[1]['exit_reason'],'TAKE_PROFIT')

    def test_stale_quote_cannot_close_position(self):
        loop, engine, store=self.setup_loop(90, stale=True)
        results=[]; loop._monitor_open_positions(results, 'cycle-1')
        self.assertEqual(results,[])
        self.assertIn('2330',engine.ledger.positions)
        self.assertEqual(store.events,[])

    def test_commit_failure_rolls_back_fill_and_degrades_persistence(self):
        loop, engine, store=self.setup_loop(97, fail_commit=True)
        before_cash=engine.ledger.cash; before_qty=engine.ledger.positions['2330'].quantity
        results=[]; loop._monitor_open_positions(results, 'cycle-1')
        self.assertEqual(results,[])
        self.assertEqual(engine.ledger.cash,before_cash)
        self.assertEqual(engine.ledger.positions['2330'].quantity,before_qty)
        self.assertTrue(engine.persistence_degraded)

    def test_same_tick_replay_is_idempotent(self):
        loop, engine, store=self.setup_loop(97)
        first=[]; loop._monitor_open_positions(first,'cycle-1')
        self.assertEqual(len(first),1)
        second=[]; loop._monitor_open_positions(second,'cycle-2')
        self.assertEqual(second,[])
        self.assertEqual(len(store.trades),1)
        self.assertEqual(len(engine.ledger.fills),2)

if __name__ == '__main__': unittest.main()
