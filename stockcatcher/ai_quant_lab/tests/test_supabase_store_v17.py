import unittest
from unittest.mock import patch
from supabase_store import SupabaseStore

class SupabaseStoreV17Tests(unittest.TestCase):
    def setUp(self): self.store = SupabaseStore(url='https://example.supabase.co', key='test-service-role')

    def test_record_event_uses_insert_once_and_database_sequence(self):
        with patch.object(self.store, '_request', return_value=[{'event_seq': 41, 'event_key': 'e1'}]) as req:
            result = self.store.record_event({'event_id':'e1','event_type':'x','occurred_at':'2026-10-17T00:00:00Z','payload':{}}, {'status':'processed'})
        self.assertTrue(result['inserted']); self.assertEqual(result['event_seq'], 41)
        self.assertEqual(req.call_args.kwargs['query'], {'on_conflict':'idempotency_key'})
        self.assertIn('ignore-duplicates', req.call_args.kwargs['prefer'])

    def test_duplicate_event_returns_original_row_without_mutation(self):
        with patch.object(self.store, '_request', return_value=[]), patch.object(self.store, 'list_rows', return_value=[{'event_seq':41,'event_key':'e1','payload':{'outcome':{'status':'processed'}}}]) as rows:
            result = self.store.record_event({'event_id':'e1','event_type':'changed','occurred_at':'2026-10-17T00:00:00Z','payload':{}}, {'status':'different'})
        self.assertFalse(result['inserted']); self.assertEqual(result['event_seq'],41)
        self.assertEqual(rows.call_args.kwargs['filters'], {'idempotency_key':'eq.e1'})

    def test_paper_trade_uses_same_idempotency_key_as_event(self):
        event = {'event_id':'signal-1','event_type':'signal.created','occurred_at':'2026-10-17T00:00:00Z','payload':{'symbol':'2330'}}
        fill = {'symbol':'2330','side':'BUY','quantity':1,'price':'100','fee':'0.14','realized_pnl':'0'}
        with patch.object(self.store, 'insert_once', return_value={'persisted':True}) as insert:
            self.store.record_trade(event, fill)
        row = insert.call_args.args[1]
        self.assertEqual(row['trade_key'], 'signal-1'); self.assertEqual(row['idempotency_key'], 'signal-1')

    def test_commit_event_uses_atomic_allowlisted_rpc(self):
        event = {'event_id':'signal-2','event_type':'signal.created','occurred_at':'2026-10-17T00:00:00Z','payload':{'symbol':'2330'}}
        fill = {'symbol':'2330','side':'BUY','quantity':1,'price':'100','fee':'0.14','realized_pnl':'0'}
        with patch.object(self.store, '_request', return_value=[{'event_seq':52,'inserted':True}]) as req:
            result = self.store.commit_event(event, {'status':'processed'}, fill)
        self.assertTrue(result['atomic']); self.assertEqual(result['event_seq'],52)
        self.assertEqual(req.call_args.args[1], 'rpc:ai_quant_lab_commit_event_and_outbox')
        self.assertEqual(req.call_args.kwargs['row']['p_trade']['idempotency_key'], 'signal-2')
        self.assertEqual(req.call_args.kwargs['row']['p_outbox']['idempotency_key'], 'paper-fill-telegram:signal-2')
        self.assertEqual(req.call_args.kwargs['row']['p_outbox']['status'], 'PENDING')

    def test_patch_requires_explicit_eq_filters(self):
        with self.assertRaises(ValueError): self.store.patch('ai_quant_lab_sessions', {'session_id':'session-id'}, {'status':'CLOSED'})

if __name__ == '__main__': unittest.main()
