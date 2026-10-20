"""Supabase-only durable adapter for AI Quant Lab. No local DB/file persistence."""
from __future__ import annotations
import json, os, urllib.request, urllib.error
from datetime import datetime, timezone
from urllib.parse import urlencode

ALLOWED_TABLES = {
    'ai_quant_lab_events', 'ai_quant_lab_paper_trades', 'ai_quant_lab_reports',
    'ai_quant_lab_sessions', 'ai_quant_lab_agent_runs', 'ai_quant_lab_checkpoints', 'ai_quant_lab_outbox'
}

class SupabaseStore:
    def __init__(self, url=None, key=None, timeout=8):
        self.url = (url or os.getenv('SUPABASE_URL', '')).rstrip('/')
        self.key = key or os.getenv('SUPABASE_SERVICE_ROLE_KEY', '')
        self.timeout = timeout

    @property
    def configured(self):
        return bool(self.url and self.key)

    def _request(self, method, table, *, query=None, row=None, prefer=None):
        if not self.configured:
            raise RuntimeError('Supabase persistence is not configured; set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY on the backend')
        if table.startswith('rpc:'):
            rpc_name = table.split(':', 1)[1]
            if rpc_name not in {'ai_quant_lab_commit_event', 'ai_quant_lab_claim_outbox', 'ai_quant_lab_notification_counts', 'ai_quant_lab_commit_event_and_outbox'}:
                raise ValueError('RPC is outside AI Quant Lab allowlist')
            url = f'{self.url}/rest/v1/rpc/{rpc_name}'
        else:
            if table not in ALLOWED_TABLES:
                raise ValueError('table is outside AI Quant Lab allowlist')
            url = f'{self.url}/rest/v1/{table}'
        if query:
            url += '?' + urlencode(query, doseq=True)
        data = None if row is None else json.dumps(row, ensure_ascii=False, default=str).encode()
        headers = {'apikey': self.key, 'Authorization': f'Bearer {self.key}', 'Accept': 'application/json'}
        if data is not None:
            headers['Content-Type'] = 'application/json'
        if prefer:
            headers['Prefer'] = prefer
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as res:
                raw = res.read()
                if not raw:
                    return []
                return json.loads(raw.decode('utf-8'))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode('utf-8', 'replace')[:500]
            raise RuntimeError(f'Supabase {method} {table} failed ({exc.code}): {detail}') from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f'Supabase connection failed: {exc.reason}') from exc

    def insert(self, table, row):
        self._request('POST', table, row=row, prefer='return=minimal')
        return {'persisted': True, 'table': table}

    def upsert(self, table, row, conflict_key):
        if conflict_key not in row:
            raise ValueError(f'upsert conflict key missing: {conflict_key}')
        rows = self._request('POST', table, query={'on_conflict': conflict_key}, row=row,
                             prefer='resolution=merge-duplicates,return=representation')
        first = rows[0] if isinstance(rows, list) and rows else {}
        return {'persisted': True, 'table': table, 'idempotent': True,
                'event_seq': first.get('event_seq'), 'row': first}

    def insert_once(self, table, row, conflict_key):
        if conflict_key not in row:
            raise ValueError(f'idempotency conflict key missing: {conflict_key}')
        rows = self._request('POST', table, query={'on_conflict': conflict_key}, row=row,
                             prefer='resolution=ignore-duplicates,return=representation')
        first = rows[0] if isinstance(rows, list) and rows else {}
        inserted = bool(first)
        if not inserted:
            existing = self.list_rows(table, select='*', limit=1,
                                      filters={conflict_key: f'eq.{row[conflict_key]}'})
            first = existing[0] if existing else {}
        return {'persisted': True, 'table': table, 'idempotent': True, 'inserted': inserted,
                'event_seq': first.get('event_seq'), 'row': first, 'run_id': first.get('run_id'),
                'session_id': first.get('session_id'), 'outbox_id': first.get('outbox_id')}

    def patch(self, table, filters, row):
        if not filters or any(not str(v).startswith('eq.') for v in filters.values()):
            raise ValueError('patch requires explicit PostgREST eq filters')
        query = {k: v for k, v in filters.items()}
        self._request('PATCH', table, query=query, row=row, prefer='return=minimal')
        return {'persisted': True, 'table': table, 'updated': True}

    def update_session(self, session_id, patch):
        return self.patch('ai_quant_lab_sessions', {'session_id': f'eq.{session_id}'}, patch)

    def update_agent_run(self, run_id, patch):
        return self.patch('ai_quant_lab_agent_runs', {'run_id': f'eq.{run_id}'}, patch)

    def upsert_agent_run(self, row):
        return self.insert_once('ai_quant_lab_agent_runs', row, 'idempotency_key')

    def enqueue_outbox(self, row):
        return self.insert_once('ai_quant_lab_outbox', row, 'idempotency_key')

    def claim_outbox(self, worker_id, limit=10, lease_seconds=45):
        rows = self._request('POST', 'rpc:ai_quant_lab_claim_outbox', row={
            'p_worker_id': str(worker_id), 'p_limit': int(limit), 'p_lease_seconds': int(lease_seconds)
        }, prefer='return=representation')
        return rows if isinstance(rows, list) else []

    def notification_counts(self):
        rows = self._request('POST', 'rpc:ai_quant_lab_notification_counts', row={}, prefer='return=representation')
        return rows if isinstance(rows, list) else []

    def enqueue_notification(self, row):
        required = ('outbox_id', 'event_id', 'destination', 'payload', 'idempotency_key')
        if any(not row.get(k) for k in required):
            raise ValueError('notification outbox row is missing required fields')
        return self.enqueue_outbox(row)

    def update_outbox(self, outbox_id, patch, *, expected_status=None, expected_worker=None):
        filters = {'outbox_id': f'eq.{outbox_id}'}
        if expected_status:
            filters['status'] = f'eq.{expected_status}'
        if expected_worker:
            filters['claimed_by'] = f'eq.{expected_worker}'
        return self.patch('ai_quant_lab_outbox', filters, patch)

    def get_outbox(self, outbox_id):
        rows = self.list_rows('ai_quant_lab_outbox', select='*', limit=1,
                              filters={'outbox_id': f'eq.{outbox_id}'})
        return rows[0] if rows else None

    def list_rows(self, table, *, select='*', order=None, limit=1000, offset=0, filters=None):
        query = {'select': select, 'limit': str(limit), 'offset': str(max(0, int(offset)))}
        if order:
            query['order'] = order
        if filters:
            query.update(filters)
        return self._request('GET', table, query=query)

    def record_event(self, event, outcome):
        payload = event.get('payload') or {}
        event_key = str(event.get('event_id', ''))
        if not event_key:
            raise ValueError('event_id is required for durable idempotency')
        return self.insert_once('ai_quant_lab_events', {
            'event_key': event_key,
            'idempotency_key': event_key,
            'schema_version': int(event.get('schema_version', 1)),
            'event_type': str(event.get('event_type', 'unknown')),
            'source': str(event.get('source', 'ai_quant_lab')),
            'symbol': str(payload.get('symbol', '')) or None,
            'stock_name': str(payload.get('stock_name', '')) or None,
            'occurred_at': event.get('occurred_at') or datetime.now(timezone.utc).isoformat(),
            'payload': {'event': event, 'outcome': outcome, 'session_id': getattr(self, 'active_session_id', None)}
        }, 'idempotency_key')

    def _trade_row(self, event, fill):
        payload = event.get('payload') or {}
        trade_key = str(event.get('event_id', ''))
        return {
            'trade_key': trade_key, 'idempotency_key': trade_key,
            'session_id': getattr(self, 'active_session_id', None),
            'symbol': fill['symbol'], 'stock_name': payload.get('stock_name'),
            'side': fill['side'], 'quantity': int(fill['quantity']), 'price': str(fill['price']),
            'fees': str(fill['fee']), 'realized_pnl': str(fill['realized_pnl']),
            'strategy': str(payload.get('strategy', 'AI_QUANT_LAB_PAPER')),
            'status': 'FILLED', 'executed_at': event.get('occurred_at') or datetime.now(timezone.utc).isoformat(),
            'metadata': {'event_id': event.get('event_id'), 'event_type': event.get('event_type'), 'source': event.get('source', 'ai_quant_lab')}
        }

    def record_trade(self, event, fill):
        return self.insert_once('ai_quant_lab_paper_trades', self._trade_row(event, fill), 'idempotency_key')

    def commit_event(self, event, outcome, fill=None):
        """Atomically persist event + optional paper fill; V18 also atomically enqueues its Telegram notice."""
        event_copy = dict(event)
        event_copy['session_id'] = getattr(self, 'active_session_id', None)
        trade = self._trade_row(event_copy, fill) if fill else None
        if fill:
            # Deterministic UUID and idempotency key bind exactly one notice to this paper-fill event.
            import uuid
            from notifications import paper_fill_text
            outbox_key = f"paper-fill-telegram:{event_copy['event_id']}"
            outbox_id = str(uuid.uuid5(uuid.NAMESPACE_URL, 'ai-quant-lab:' + outbox_key))
            payload = event_copy.get('payload') or {}
            outbox = {'outbox_id': outbox_id, 'session_id': event_copy.get('session_id'),
                      'event_id': str(event_copy['event_id']), 'destination': 'TELEGRAM',
                      'payload': {'text': paper_fill_text(fill, payload.get('stock_name') or payload.get('name')),
                                  'notification_type': 'PAPER_FILL', 'symbol': fill.get('symbol'),
                                  'side': fill.get('side'), 'mode': 'paper'},
                      'status': 'PENDING', 'idempotency_key': outbox_key, 'max_attempts': 8, 'priority': 20}
            body = {'p_event': event_copy, 'p_outcome': outcome, 'p_trade': trade, 'p_outbox': outbox}
            rows = self._request('POST', 'rpc:ai_quant_lab_commit_event_and_outbox', row=body, prefer='return=representation')
        else:
            body = {'p_event': event_copy, 'p_outcome': outcome, 'p_trade': None}
            rows = self._request('POST', 'rpc:ai_quant_lab_commit_event', row=body, prefer='return=representation')
        first = rows[0] if isinstance(rows, list) and rows else (rows if isinstance(rows, dict) else {})
        return {'persisted': True, 'table': 'ai_quant_lab_events', 'event_seq': first.get('event_seq'),
                'inserted': first.get('inserted', True), 'outbox_inserted': first.get('outbox_inserted'),
                'notification_outbox': bool(fill), 'atomic': True}

    def record_report(self, report_key, report_date, report):
        row = {
            'report_key': report_key, 'report_type': 'DAILY_RESEARCH', 'report_date': report_date,
            'title': f'天機 AI Quant Lab 每日報告 — {report_date}',
            'summary': f"事件 {report.get('event_count', 0)} 筆；模擬成交 {len(report.get('fills_today', []))} 筆",
            'metrics': {'event_count': report.get('event_count', 0), 'processed_count': report.get('processed_count', 0), 'rejected_or_error_count': report.get('rejected_or_error_count', 0)},
            'body': report, 'status': 'READY'
        }
        self._request('POST', 'ai_quant_lab_reports', query={'on_conflict': 'report_key'}, row=row, prefer='resolution=merge-duplicates,return=minimal')
        return {'persisted': True, 'table': 'ai_quant_lab_reports'}

    def record_research_report(self, report_key, report_date, title, summary, report_type, report):
        """Persist a Lab-owned research/validation report; never writes production tables."""
        row = {
            'report_key': str(report_key), 'report_type': str(report_type), 'report_date': str(report_date),
            'title': str(title)[:240], 'summary': str(summary)[:1000],
            'metrics': {'paper_orders_created': int(report.get('paper_orders_created', 0)),
                        'actual_horizon_trading_days': int(report.get('actual_horizon_trading_days', 0))},
            'body': report, 'status': 'READY'
        }
        self._request('POST', 'ai_quant_lab_reports', query={'on_conflict': 'report_key'}, row=row,
                      prefer='resolution=merge-duplicates,return=minimal')
        return {'persisted': True, 'table': 'ai_quant_lab_reports', 'report_key': str(report_key)}
