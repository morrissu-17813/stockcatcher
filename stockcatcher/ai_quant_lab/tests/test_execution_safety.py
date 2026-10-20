import sys
import unittest
from pathlib import Path
from datetime import datetime, timedelta, timezone
from decimal import Decimal
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from execution_safety import (OrderStatus, PaperOrder, OrderRegistry, market_data_block_reason,
                              calculate_slippage, exit_trigger)

class ExecutionSafetyTests(unittest.TestCase):
    def test_stale_flag_and_old_snapshot_fail_closed(self):
        self.assertEqual(market_data_block_reason({'stale': True}), 'MARKET_DATA_STALE')
        old = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        self.assertEqual(market_data_block_reason({'observed_at': old}), 'MARKET_TIMESTAMP_STALE')
        self.assertIsNone(market_data_block_reason({'data_age_seconds': 2}))

    def test_order_registry_deduplicates_idempotency_key(self):
        registry = OrderRegistry()
        first = PaperOrder('o1', 'signal-123', '2330', 'BUY', 10)
        second = PaperOrder('o2', 'signal-123', '2330', 'BUY', 10)
        saved, created = registry.create(first)
        same, created_again = registry.create(second)
        self.assertTrue(created)
        self.assertFalse(created_again)
        self.assertIs(saved, same)

    def test_partial_fill_then_complete_tracks_weighted_average(self):
        order = PaperOrder('o1', 'k1', '2330', 'BUY', 10)
        order.accept()
        order.fill(4, Decimal('100'))
        self.assertEqual(order.status, OrderStatus.PARTIALLY_FILLED)
        self.assertEqual(order.remaining_quantity, 6)
        order.fill(6, Decimal('103'))
        self.assertEqual(order.status, OrderStatus.FILLED)
        self.assertEqual(order.average_fill_price, Decimal('101.8'))

    def test_unknown_order_requires_reconciliation_not_resubmit(self):
        order = PaperOrder('o1', 'k1', '2330', 'BUY', 10)
        order.accept(); order.mark_unknown('timeout after submit')
        self.assertEqual(order.status, OrderStatus.UNKNOWN)
        with self.assertRaisesRegex(ValueError, 'accepted, open'):
            order.fill(10, Decimal('100'))

    def test_slippage_is_adverse_direction_aware(self):
        buy = calculate_slippage(Decimal('100'), Decimal('101'), 'BUY')
        sell = calculate_slippage(Decimal('100'), Decimal('99'), 'SELL')
        self.assertEqual(buy['adverse_bps'], '100.00')
        self.assertEqual(sell['adverse_bps'], '100.00')

    def test_stop_loss_and_take_profit(self):
        self.assertEqual(exit_trigger(Decimal('100'), Decimal('98')), 'STOP_LOSS')
        self.assertEqual(exit_trigger(Decimal('100'), Decimal('104')), 'TAKE_PROFIT')
        self.assertIsNone(exit_trigger(Decimal('100'), Decimal('101')))

if __name__ == '__main__':
    unittest.main()

class EngineTradeSafetyTests(unittest.TestCase):
    def test_engine_rejects_stale_market_snapshot_before_fill(self):
        from engine import LabEngine
        class Store:
            configured = True
            def list_rows(self, *a, **k): return []
            def record_event(self, *a): return {'persisted': True}
            def record_trade(self, *a): return {'persisted': True}
        engine = LabEngine(store=Store())
        outcome = engine.process({'event_id':'stale-1','event_type':'signal.created',
            'occurred_at':datetime.now(timezone.utc).isoformat(), 'payload':{
                'mode':'paper','symbol':'2330','side':'BUY','quantity':1,'price':'100',
                'market_snapshot':{'stale':True,'data_age_seconds':999}}})
        self.assertIn(outcome['status'], ('rejected','error'))
        self.assertEqual(engine.ledger.positions.get('2330').quantity if engine.ledger.positions.get('2330') else 0, 0)

    def test_engine_rejects_duplicate_buy_while_position_open(self):
        from engine import LabEngine
        class Store:
            configured = True
            def list_rows(self, *a, **k): return []
            def record_event(self, *a): return {'persisted': True}
            def record_trade(self, *a): return {'persisted': True}
        engine = LabEngine(store=Store())
        def event(eid):
            return {'event_id':eid,'event_type':'signal.created','occurred_at':datetime.now(timezone.utc).isoformat(),
                    'payload':{'mode':'paper','symbol':'2330','side':'BUY','quantity':1,'price':'100'}}
        self.assertEqual(engine.process(event('buy-1'))['status'], 'processed')
        second = engine.process(event('buy-2'))
        self.assertEqual(second['status'], 'rejected')
        self.assertEqual(engine.ledger.positions['2330'].quantity, 1)
