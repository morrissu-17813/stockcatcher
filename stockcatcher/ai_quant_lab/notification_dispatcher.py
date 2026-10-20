"""Durable Supabase Outbox worker. Telegram is notification-only; never submits broker orders."""
from __future__ import annotations
import os, time, uuid, random, threading
from datetime import datetime, timezone
from notifications import TelegramTransport, DeliveryOutcomeUnknown


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def backoff_seconds(attempt: int, retry_after: int | None = None, base: float = 2.0, cap: float = 900.0) -> int:
    if retry_after is not None:
        return max(1, min(int(retry_after), 3600))
    return max(1, min(int(cap), int(min(cap, base * (2 ** max(0, min(attempt - 1, 10)))) * random.uniform(0.8, 1.2))))


class DurableNotificationDispatcher:
    def __init__(self, store, transport=None, worker_id=None, poll_seconds=2.0, batch_size=10, lease_seconds=45):
        self.store = store
        self.transport = transport or TelegramTransport()
        self.worker_id = worker_id or f'lab-notifier-{uuid.uuid4()}'
        self.poll_seconds = max(0.5, float(poll_seconds))
        self.batch_size = max(1, min(int(batch_size), 100))
        self.lease_seconds = max(10, min(int(lease_seconds), 300))
        self.stop_event = threading.Event()
        self.thread = None
        self.stats = {'claimed': 0, 'sent': 0, 'retry_pending': 0, 'dead_letter': 0, 'unknown': 0, 'suppressed': 0, 'last_success_at': None, 'last_error': None}
        self._lock = threading.Lock()

    @property
    def enabled(self):
        return bool(self.store and self.store.configured and self.transport.configured)

    def start(self):
        if not self.enabled:
            return {'started': False, 'reason': 'SUPABASE_OR_TELEGRAM_NOT_CONFIGURED'}
        if self.thread and self.thread.is_alive():
            return {'started': True, 'already_running': True, 'worker_id': self.worker_id}
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._run, name='ai-quant-lab-notification-dispatcher', daemon=True)
        self.thread.start()
        return {'started': True, 'worker_id': self.worker_id}

    def stop(self, timeout=3):
        self.stop_event.set()
        if self.thread and self.thread.is_alive(): self.thread.join(timeout=timeout)
        return {'stopped': not bool(self.thread and self.thread.is_alive())}

    def _inc(self, key, value=1):
        with self._lock: self.stats[key] = self.stats.get(key, 0) + value

    def status(self):
        with self._lock: local = dict(self.stats)
        try:
            counts = self.store.notification_counts() if self.store and self.store.configured else []
            return {'ok': bool(self.enabled), 'enabled': bool(self.enabled), 'worker_id': self.worker_id,
                    'worker_alive': bool(self.thread and self.thread.is_alive()), 'stats': local,
                    'queue': counts, 'semantics': 'at-least-once with UNKNOWN state for ambiguous Telegram outcomes',
                    'paper_only': True}
        except Exception as exc:
            return {'ok': False, 'enabled': bool(self.enabled), 'worker_id': self.worker_id,
                    'worker_alive': bool(self.thread and self.thread.is_alive()), 'stats': local,
                    'error': f'{type(exc).__name__}: {str(exc)[:240]}', 'paper_only': True}

    def dispatch_once(self):
        jobs = self.store.claim_outbox(self.worker_id, self.batch_size, self.lease_seconds)
        self._inc('claimed', len(jobs))
        outcomes = []
        for job in jobs:
            outbox_id = job.get('outbox_id'); attempt = int(job.get('attempts') or 1)
            payload = job.get('payload') or {}
            if job.get('destination') != 'TELEGRAM' or not payload.get('text'):
                self.store.update_outbox(outbox_id, {'status':'DEAD_LETTER','last_error':'UNSUPPORTED_DESTINATION_OR_EMPTY_PAYLOAD','dead_lettered_at':utcnow(),'lease_expires_at':None,'claimed_by':None,'updated_at':utcnow()}, expected_status='SENDING', expected_worker=self.worker_id)
                self._inc('dead_letter'); outcomes.append({'outbox_id':outbox_id,'status':'DEAD_LETTER'}); continue
            try:
                result = self.transport.send(payload['text'])
            except DeliveryOutcomeUnknown as exc:
                # Never auto-retry an ambiguous send: Telegram might already have accepted it.
                self.store.update_outbox(outbox_id, {'status':'UNKNOWN','last_error':str(exc)[:500],
                    'lease_expires_at':None,'claimed_by':None,'updated_at':utcnow(),
                    'response_metadata':{'outcome':'ambiguous','attempt':attempt}}, expected_status='SENDING', expected_worker=self.worker_id)
                self._inc('unknown'); outcomes.append({'outbox_id':outbox_id,'status':'UNKNOWN'}); continue
            except Exception as exc:
                # Unexpected internal errors are retryable only while attempts remain.
                self._failure(job, f'{type(exc).__name__}: {exc}', retry_after=None, transient=True)
                outcomes.append({'outbox_id':outbox_id,'status':'RETRY_PENDING' if attempt < int(job.get('max_attempts') or 8) else 'DEAD_LETTER'}); continue
            if result.accepted:
                self.store.update_outbox(outbox_id, {'status':'SENT','external_message_id':result.message_id,
                    'sent_at':utcnow(),'delivered_at':utcnow(),'lease_expires_at':None,'claimed_by':None,
                    'last_error':None,'response_metadata':{'telegram_accepted':True},'updated_at':utcnow()}, expected_status='SENDING', expected_worker=self.worker_id)
                self._inc('sent');
                with self._lock: self.stats['last_success_at'] = utcnow(); self.stats['last_error'] = None
                outcomes.append({'outbox_id':outbox_id,'status':'SENT','message_id':result.message_id}); continue
            retryable = result.error_code == '429' or (str(result.error_code).isdigit() and int(result.error_code) >= 500)
            self._failure(job, f'{result.error_code}: {result.error_description}', result.retry_after, retryable)
            status = 'RETRY_PENDING' if retryable and attempt < int(job.get('max_attempts') or 8) else 'DEAD_LETTER'
            outcomes.append({'outbox_id':outbox_id,'status':status})
        return {'claimed':len(jobs),'outcomes':outcomes}

    def _failure(self, job, error, retry_after, transient):
        attempt = int(job.get('attempts') or 1); maximum = int(job.get('max_attempts') or 8); oid = job['outbox_id']
        now = utcnow()
        if transient and attempt < maximum:
            delay = backoff_seconds(attempt, retry_after)
            from datetime import timedelta
            available = (datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat()
            self.store.update_outbox(oid, {'status':'RETRY_PENDING','available_at':available,'last_error':str(error)[:500],
                'lease_expires_at':None,'claimed_by':None,'updated_at':now,'response_metadata':{'retry_delay_seconds':delay,'attempt':attempt}}, expected_status='SENDING', expected_worker=self.worker_id)
            self._inc('retry_pending')
        else:
            self.store.update_outbox(oid, {'status':'DEAD_LETTER','last_error':str(error)[:500],
                'dead_lettered_at':now,'lease_expires_at':None,'claimed_by':None,'updated_at':now,
                'response_metadata':{'transient':bool(transient),'attempt':attempt}}, expected_status='SENDING', expected_worker=self.worker_id)
            self._inc('dead_letter')
        with self._lock: self.stats['last_error'] = str(error)[:240]

    def _run(self):
        while not self.stop_event.is_set():
            try:
                self.dispatch_once()
            except Exception as exc:
                with self._lock: self.stats['last_error'] = f'{type(exc).__name__}: {str(exc)[:240]}'
            self.stop_event.wait(self.poll_seconds)
