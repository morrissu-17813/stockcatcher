import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from event_adapter.signal_feed import TianjiSignalFeed


def test_signal_feed_missing_path_fails_closed(tmp_path):
    feed=TianjiSignalFeed(tmp_path/'missing')
    status=feed.scan()
    assert status['path_exists'] is False
    assert status['last_error']
    assert status['signals'] == []


def test_signal_feed_reads_prediction_records_read_only(tmp_path):
    path=tmp_path/'predictions'/'2026-10-17'/'2330'/'events.jsonl'
    path.parent.mkdir(parents=True)
    row={'event_type':'INTRADAY_3K_PREDICTION','prediction_id':'p1','symbol':'2330','trade_date':'2026-10-17','created_at':'2026-10-17T10:00:00+08:00','notification_status':'sent','trigger_snapshot':{'price':100}}
    path.write_text(json.dumps(row),encoding='utf-8')
    feed=TianjiSignalFeed(tmp_path)
    status=feed.scan()
    assert status['new_signal_count']==1
    assert status['signals'][0]['symbol']=='2330'
    assert status['signals'][0]['read_only'] is True
    assert feed.scan()['new_signal_count']==1
