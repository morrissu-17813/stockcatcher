import unittest
from unittest.mock import Mock
from notification_dispatcher import DurableNotificationDispatcher, backoff_seconds
from notifications import TelegramResult, DeliveryOutcomeUnknown

class FakeStore:
    configured = True
    def __init__(self, jobs): self.jobs=list(jobs); self.updates=[]
    def claim_outbox(self, worker, limit, lease): jobs,self.jobs=self.jobs,[]; return jobs
    def update_outbox(self, oid, patch, expected_status=None, expected_worker=None): self.updates.append((oid,patch,expected_status,expected_worker)); return {'persisted':True}
    def notification_counts(self): return [{'status':'PENDING','count':0,'oldest_created_at':None}]

class FakeTransport:
    configured = True
    def __init__(self, result=None, error=None): self.result=result; self.error=error; self.calls=0
    def send(self, text):
        self.calls += 1
        if self.error: raise self.error
        return self.result

def job(**patch):
    base={'outbox_id':'o1','destination':'TELEGRAM','payload':{'text':'paper only'},'attempts':1,'max_attempts':8,'status':'SENDING'}
    base.update(patch); return base

class DispatcherTests(unittest.TestCase):
    def test_success_marks_sent_and_records_external_message_id(self):
        store=FakeStore([job()]); transport=FakeTransport(TelegramResult(True, message_id='123'))
        d=DurableNotificationDispatcher(store,transport)
        result=d.dispatch_once()
        self.assertEqual(result['outcomes'][0]['status'],'SENT')
        self.assertEqual(store.updates[0][1]['external_message_id'],'123')
        self.assertEqual(store.updates[0][2],'SENDING')

    def test_ambiguous_transport_marks_unknown_never_retries_automatically(self):
        store=FakeStore([job()]); transport=FakeTransport(error=DeliveryOutcomeUnknown('timeout'))
        d=DurableNotificationDispatcher(store,transport)
        result=d.dispatch_once()
        self.assertEqual(result['outcomes'][0]['status'],'UNKNOWN')
        self.assertEqual(store.updates[0][1]['status'],'UNKNOWN')
        self.assertEqual(transport.calls,1)  # attempted once; ambiguous outcomes are not automatically retried

    def test_retryable_error_schedules_retry(self):
        store=FakeStore([job()]); transport=FakeTransport(TelegramResult(False,error_code='429',error_description='slow down',retry_after=5))
        d=DurableNotificationDispatcher(store,transport)
        result=d.dispatch_once()
        self.assertEqual(result['outcomes'][0]['status'],'RETRY_PENDING')
        self.assertEqual(store.updates[0][1]['response_metadata']['retry_delay_seconds'],5)

    def test_nonretryable_error_goes_dead_letter(self):
        store=FakeStore([job()]); transport=FakeTransport(TelegramResult(False,error_code='400',error_description='bad chat'))
        d=DurableNotificationDispatcher(store,transport)
        result=d.dispatch_once()
        self.assertEqual(result['outcomes'][0]['status'],'DEAD_LETTER')
        self.assertEqual(store.updates[0][1]['status'],'DEAD_LETTER')

    def test_max_attempts_goes_dead_letter_even_for_5xx(self):
        store=FakeStore([job(attempts=8,max_attempts=8)]); transport=FakeTransport(TelegramResult(False,error_code='503',error_description='down'))
        d=DurableNotificationDispatcher(store,transport)
        result=d.dispatch_once()
        self.assertEqual(result['outcomes'][0]['status'],'DEAD_LETTER')

    def test_backoff_respects_retry_after_and_caps(self):
        self.assertEqual(backoff_seconds(1, retry_after=17),17)
        self.assertLessEqual(backoff_seconds(100),900)

if __name__ == '__main__': unittest.main()
