import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine import LabEngine

class FakeSupabaseStore:
    """Contract test double; does not contact the network or persist local files."""
    configured = True
    def __init__(self):
        self.events = []
        self.trades = []
        self.reports = []
    def list_rows(self, table, select='*', order=None, limit=1000, offset=0):
        if table == 'ai_quant_lab_paper_trades':
            return list(self.trades)
        if table == 'ai_quant_lab_events':
            return list(reversed(self.events))
        return list(self.reports)
    def record_trade(self, event, fill):
        if any(x['trade_key'] == event['event_id'] for x in self.trades):
            raise RuntimeError('duplicate trade key')
        self.trades.append({'trade_key':event['event_id'],'symbol':fill['symbol'],'side':fill['side'],'quantity':fill['quantity'],'price':fill['price'],'status':'FILLED','executed_at':event['occurred_at']})
        return {'persisted':True,'table':'ai_quant_lab_paper_trades'}
    def record_event(self, event, outcome):
        self.events.append({'event_key':event['event_id'],'event_type':event['event_type'],'source':event.get('source','test'),'occurred_at':event['occurred_at'],'payload':{'event':event,'outcome':outcome},'created_at':event['occurred_at']})
        return {'persisted':True,'table':'ai_quant_lab_events'}
    def record_report(self, key, date, report):
        self.reports.append({'report_key':key,'report_date':date,'body':report})
        return {'persisted':True,'table':'ai_quant_lab_reports'}

class SupabasePersistenceTests(unittest.TestCase):
    def setUp(self):
        self.store = FakeSupabaseStore()
        self.event = {'event_id':'persist-1','event_type':'signal.created','occurred_at':'2026-10-16T09:00:00+08:00','source':'test','payload':{'mode':'paper','symbol':'2330','side':'BUY','quantity':10,'price':'100'}}
    def test_fill_and_event_are_sent_to_supabase_adapter(self):
        engine = LabEngine(store=self.store, max_order_notional='10000')
        result = engine.process(self.event)
        self.assertEqual(result['status'],'processed')
        self.assertEqual(result['persistence'],'supabase')
        self.assertEqual(sum(e['event_type'] == 'signal.created' for e in self.store.events),1)
        self.assertGreaterEqual(sum(e['event_type'] == 'agent.state_changed' for e in self.store.events),1)
        self.assertEqual(len(self.store.trades),1)
    def test_agent_state_event_includes_target_zone_and_bubble(self):
        engine = LabEngine(store=self.store, max_order_notional='10000')
        engine.agent_task('quant', 'working', '檢查 2330 的突破與量能')
        event = next(e for e in self.store.events if e['event_type'] == 'agent.state_changed')
        payload = event['payload']['event']['payload']
        self.assertEqual(payload['agent_id'], 'quant')
        self.assertEqual(payload['target_zone'], 'ANALYST_DESKS')
        self.assertIn('突破與量能', payload['bubble'])
        self.assertEqual(engine.state()['roles'][1]['target_zone'], 'ANALYST_DESKS')

    def test_restart_rebuilds_paper_positions_and_deduplicates(self):
        first = LabEngine(store=self.store, max_order_notional='10000')
        first.process(self.event)
        restarted = LabEngine(store=self.store, max_order_notional='10000')
        self.assertEqual(restarted.state()['counts']['fills'],1)
        self.assertEqual(restarted.state()['ledger']['positions'][0]['quantity'],10)
        self.assertEqual(restarted.process(self.event)['status'],'duplicate')
        self.assertEqual(len(self.store.trades),1)
    def test_durable_write_failure_rolls_back_and_marks_engine_degraded(self):
        class FailingStore(FakeSupabaseStore):
            def record_trade(self, event, fill): raise RuntimeError('simulated trade persistence failure')
            def record_event(self, event, outcome): raise RuntimeError('simulated event persistence failure')
        store = FailingStore()
        engine = LabEngine(store=store, max_order_notional='10000')
        result = engine.process(self.event)
        self.assertEqual(result['status'], 'persistence_error')
        self.assertTrue(engine.persistence_degraded)
        self.assertEqual(engine.ledger.snapshot()['fills'], [])

    def test_report_is_persisted_via_store_contract(self):
        engine = LabEngine(store=self.store)
        report = engine.generate_report('2026-10-16')
        self.assertEqual(report['persistence'],'supabase')
        self.assertEqual(self.store.reports[0]['report_key'],'daily-2026-10-16')

if __name__ == '__main__': unittest.main()
