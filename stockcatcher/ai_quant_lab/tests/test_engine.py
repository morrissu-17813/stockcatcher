import json, sys, tempfile, unittest
from decimal import Decimal
from pathlib import Path
from datetime import datetime
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine import LabEngine

class EngineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.engine = LabEngine(self.root / 'ignored-db-path' , max_order_notional='10000')
    def tearDown(self): self.tmp.cleanup()
    def event(self, event_id='evt-1', **payload):
        return {'event_id': event_id, 'event_type': 'signal.created', 'occurred_at': '2026-10-16T09:00:00+08:00', 'source': 'test', 'payload': {'mode':'paper','symbol':'2330','side':'BUY','quantity':10,'price':'100', **payload}}
    def test_signal_creates_in_memory_paper_fill(self):
        result = self.engine.process(self.event())
        self.assertEqual(result['status'], 'processed')
        self.assertEqual(result['fill']['quantity'], 10)
        self.assertEqual(self.engine.state()['counts']['fills'], 1)
    def test_duplicate_event_does_not_duplicate_fill(self):
        self.engine.process(self.event())
        result = self.engine.process(self.event())
        self.assertEqual(result['status'], 'duplicate')
        self.assertEqual(self.engine.state()['counts']['fills'], 1)
    def test_live_or_unmarked_signal_rejected(self):
        e = self.event(); e['payload'].pop('mode')
        result = self.engine.process(e)
        self.assertIn("mode must explicitly be 'paper'", result['error'])
        self.assertEqual(self.engine.state()['counts']['fills'], 0)
    def test_risk_limit_rejects_large_order(self):
        result = self.engine.process(self.event(quantity=200))
        self.assertEqual(result['status'], 'rejected')
        self.assertEqual(self.engine.state()['counts']['fills'], 0)
    def test_new_engine_starts_empty_without_durable_store(self):
        self.engine.process(self.event())
        restarted = LabEngine(self.root / 'ignored-db-path-2', max_order_notional='10000')
        self.assertEqual(restarted.state()['counts']['fills'], 0)
        self.assertFalse((self.root / 'ignored-db-path-2').exists())
    def test_restore_replays_persisted_fees_not_current_fee_rate(self):
        class RestoreStore:
            configured = True
            def list_rows(self, table, **kwargs):
                if table == 'ai_quant_lab_paper_trades':
                    return [
                        {'trade_key':'buy1','symbol':'2330','side':'BUY','quantity':10,'price':'100','fees':'0.25','status':'FILLED','executed_at':'2026-10-16T09:00:00+08:00'},
                        {'trade_key':'sell1','symbol':'2330','side':'SELL','quantity':10,'price':'110','fees':'0.30','status':'FILLED','executed_at':'2026-10-16T10:00:00+08:00'},
                    ]
                if table == 'ai_quant_lab_events': return []
                return []
        restored = LabEngine(store=RestoreStore(), fee_rate='0.01')
        self.assertIsNone(restored.restore_error)
        self.assertEqual(len(restored.ledger.fills), 2)
        self.assertEqual(restored.ledger.fills[0].fee, Decimal('0.25'))
        self.assertEqual(restored.ledger.fills[1].fee, Decimal('0.30'))
        self.assertEqual(restored.ledger.snapshot()['cash'], '1000099.45')
        self.assertEqual(restored.ledger.snapshot()['realized_pnl'], '99.45')

    def test_paper_exit_check_triggers_stop_loss_and_closes_position(self):
        buy = self.engine.process(self.event('buy-exit', quantity=10, price='100'))
        self.assertEqual(buy['status'], 'processed')
        exit_event = {'event_id':'stop-exit-1','event_type':'paper.exit_check',
            'occurred_at':'2026-10-16T10:00:00+08:00','source':'test',
            'payload':{'mode':'paper','symbol':'2330','mark_price':'97',
                       'market_snapshot':{'data_age_seconds':1}}}
        result = self.engine.process(exit_event)
        self.assertEqual(result['status'], 'processed')
        self.assertEqual(result['exit_reason'], 'STOP_LOSS')
        self.assertEqual(result['fill']['side'], 'SELL')
        self.assertEqual(result['fill']['quantity'], 10)
        self.assertEqual(self.engine.ledger.positions['2330'].quantity, 0)

    def test_paper_exit_check_requires_fresh_market_snapshot(self):
        self.engine.process(self.event('buy-exit-stale', quantity=1, price='100'))
        event = {'event_id':'exit-stale-1','event_type':'paper.exit_check',
            'occurred_at':'2026-10-16T10:00:00+08:00','payload':{
                'mode':'paper','symbol':'2330','mark_price':'97',
                'market_snapshot':{'stale':True,'data_age_seconds':999}}}
        result = self.engine.process(event)
        self.assertIn(result['status'], ('rejected', 'error'))
        self.assertEqual(self.engine.ledger.positions['2330'].quantity, 1)

    def test_paper_exit_check_does_not_sell_when_no_trigger(self):
        self.engine.process(self.event('buy-no-exit', quantity=1, price='100'))
        event = {'event_id':'exit-no-trigger','event_type':'paper.exit_check',
            'occurred_at':'2026-10-16T10:00:00+08:00','payload':{
                'mode':'paper','symbol':'2330','mark_price':'101',
                'market_snapshot':{'data_age_seconds':1}}}
        result = self.engine.process(event)
        self.assertEqual(result['status'], 'processed')
        self.assertIn('exit_not_triggered', result['actions'])
        self.assertEqual(self.engine.ledger.positions['2330'].quantity, 1)

    def test_report_returns_data_without_local_persistence(self):
        self.engine.process(self.event())
        report = self.engine.generate_report('2026-10-16')
        self.assertIsInstance(report, dict)
        self.assertEqual(report['event_count'], 1)
        self.assertFalse(report['safety']['live_orders_enabled'])
        self.assertEqual(report['persistence'], 'memory-only-dev')

if __name__ == '__main__': unittest.main()
