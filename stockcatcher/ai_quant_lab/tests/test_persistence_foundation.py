import copy
import json
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path

from persistence_foundation import PersistenceFoundation, make_idempotency_key, sha256_json


class FakeStore:
    configured = True
    def __init__(self):
        self.tables = {name: [] for name in (
            'ai_quant_lab_sessions', 'ai_quant_lab_agent_runs', 'ai_quant_lab_checkpoints',
            'ai_quant_lab_events', 'ai_quant_lab_paper_trades', 'ai_quant_lab_outbox')}
    def list_rows(self, table, *, select='*', order=None, limit=1000, offset=0, filters=None):
        rows = list(self.tables[table])
        if filters:
            for key, val in filters.items():
                op, expected = val.split('.', 1)
                if op == 'eq': rows = [r for r in rows if str(r.get(key)) == expected]
                elif op == 'gt': rows = [r for r in rows if int(r.get(key) or 0) > int(expected)]
        if order:
            key, _, direction = order.partition('.')
            rows.sort(key=lambda r: r.get(key) or 0, reverse=direction == 'desc')
        return copy.deepcopy(rows[offset:offset+limit])
    def insert(self, table, row):
        if table == 'ai_quant_lab_events' and any(x.get('idempotency_key') == row.get('idempotency_key') for x in self.tables[table]):
            raise RuntimeError('duplicate idempotency key')
        self.tables[table].append(copy.deepcopy(row)); return {'persisted': True}
    def update_session(self, sid, patch):
        for row in self.tables['ai_quant_lab_sessions']:
            if row['session_id'] == sid: row.update(copy.deepcopy(patch)); return {'persisted': True}
        return {'persisted': True, 'updated': False}
    def update_agent_run(self, rid, patch):
        for row in self.tables['ai_quant_lab_agent_runs']:
            if row['run_id'] == rid: row.update(copy.deepcopy(patch)); return {'persisted': True}
        return {'persisted': True, 'updated': False}
    def upsert_agent_run(self, row):
        for existing in self.tables['ai_quant_lab_agent_runs']:
            if existing['idempotency_key'] == row['idempotency_key']:
                return {'persisted': True, 'inserted': False, 'row': copy.deepcopy(existing)}
        self.tables['ai_quant_lab_agent_runs'].append(copy.deepcopy(row)); return {'persisted': True, 'inserted': True, 'row': row}


class FakeEngine:
    def __init__(self):
        self.roles = {rid: {'role_id': rid, 'status': 'idle', 'task': 'waiting'} for rid in ('cio','quant','research','risk','execution','auditor')}


class PersistenceFoundationTests(unittest.TestCase):
    def test_session_starts_with_parent_link_and_durable_status(self):
        store = FakeStore(); first = PersistenceFoundation(store, runtime_id='runtime-1')
        started = first.start()
        self.assertTrue(started['ok']); self.assertTrue(started['durable'])
        self.assertEqual(store.tables['ai_quant_lab_sessions'][0]['status'], 'RUNNING')
        first.close()
        second = PersistenceFoundation(store, runtime_id='runtime-2')
        result = second.start()
        self.assertTrue(result['ok'])
        self.assertEqual(result['parent_session_id'], started['session_id'])

    def test_live_session_blocks_second_runtime(self):
        store = FakeStore(); first = PersistenceFoundation(store, runtime_id='one'); first.start()
        second = PersistenceFoundation(store, runtime_id='two')
        result = second.start()
        self.assertFalse(result['ok']); self.assertEqual(result['status'], 'BLOCKED_DUPLICATE_RUNTIME')
        self.assertEqual(len(store.tables['ai_quant_lab_sessions']), 1)

    def test_checkpoint_hash_and_restore_state_projection(self):
        store = FakeStore(); mgr = PersistenceFoundation(store); mgr.start()
        state = {'roles': [{'role_id':'quant','status':'success','task':'validated','target_zone':'ANALYST_DESKS'}]}
        cp = mgr.create_checkpoint(state, last_event_seq=5)
        self.assertTrue(cp['ok'])
        saved = mgr.latest_valid_checkpoint()
        self.assertEqual(saved['checkpoint_id'], cp['checkpoint_id'])
        store.tables['ai_quant_lab_events'].append({'event_seq':6,'event_type':'agent.state_changed',
            'payload': {'event': {'occurred_at':'2026-10-17T00:00:00Z','payload': {'agent_id':'risk','status':'warning','task':'check','target_zone':'RISK_OFFICE'}}}})
        engine = FakeEngine(); restored = mgr.restore_into(engine)
        self.assertTrue(restored['checkpoint_restored'])
        self.assertEqual(engine.roles['quant']['task'], 'validated')
        self.assertEqual(engine.roles['risk']['status'], 'warning')
        self.assertEqual(restored['events_replayed'], 1)

    def test_corrupt_checkpoint_is_ignored(self):
        store = FakeStore(); mgr = PersistenceFoundation(store); mgr.start()
        cp = mgr.create_checkpoint({'roles': []}, 0)
        store.tables['ai_quant_lab_checkpoints'][0]['state_json'] = {'roles': [{'role_id':'cio'}]}
        self.assertIsNone(mgr.latest_valid_checkpoint())

    def test_expired_agent_run_is_requeued_on_recovery(self):
        store = FakeStore()
        store.tables['ai_quant_lab_agent_runs'].append({'run_id':'run-1','status':'RUNNING','lease_expires_at':'2000-01-01T00:00:00+00:00','updated_at':'2000-01-01T00:00:00+00:00'})
        mgr = PersistenceFoundation(store); result = mgr.start()
        self.assertTrue(result['ok']); self.assertEqual(result['interrupted_runs'], 1)
        self.assertEqual(store.tables['ai_quant_lab_agent_runs'][0]['status'], 'RETRY_PENDING')

    def test_idempotency_key_is_stable_and_namespaced(self):
        a = make_idempotency_key('event', 'prediction-1', 'validation')
        b = make_idempotency_key('event', 'prediction-1', 'validation')
        c = make_idempotency_key('trade', 'prediction-1', 'validation')
        self.assertEqual(a, b); self.assertNotEqual(a, c)
        self.assertEqual(len(sha256_json({'b':2,'a':1})), 64)

    def test_missing_supabase_fails_closed(self):
        class NoStore: configured = False
        mgr = PersistenceFoundation(NoStore())
        result = mgr.start()
        self.assertFalse(result['ok']); self.assertFalse(result['durable'])

    def test_migration_is_additive_and_contains_session_checkpoint_outbox(self):
        sql = Path(__file__).parents[1].joinpath('supabase/migrations/202610170001_v17_persistence_foundation.sql').read_text()
        for token in ('ai_quant_lab_sessions','ai_quant_lab_agent_runs','ai_quant_lab_checkpoints','ai_quant_lab_outbox','event_seq','idempotency_key','begin;','commit;'):
            self.assertIn(token, sql)
        self.assertNotIn('drop table', sql.lower())
        self.assertNotIn('truncate ', sql.lower())

if __name__ == '__main__': unittest.main()
