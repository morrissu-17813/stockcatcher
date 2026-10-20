import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from event_adapter.production_reader import iter_production_events


class ProductionReaderTests(unittest.TestCase):
    def test_reads_prediction_and_validation_without_mutating_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "production"
            day = root / "predictions" / "2026-10-16" / "2330"
            day.mkdir(parents=True)
            events_path = day / "events.jsonl"
            prediction = {
                "prediction_id": "20261016-2330-abc123", "trade_date": "2026-10-16", "symbol": "2330",
                "event_type": "INTRADAY_3K_PREDICTION", "created_at": "2026-10-16T09:15:00+08:00",
                "context": {"score": 72}, "trigger_snapshot": {"current_price": 100}, "volume_snapshot": {"ratio": 2.1},
                "notification_status": "SENT", "schema_version": "prediction-v2.1"
            }
            events_path.write_text(json.dumps(prediction) + "\n", encoding="utf-8")
            before = events_path.read_bytes()
            gt_path = day / "ground_truth.json"
            gt_path.write_text(json.dumps({"trade_date":"2026-10-16", "symbol":"2330", "ground_truth_3k": True, "close": 105, "validated_at":"2026-10-16T13:33:00+08:00"}), encoding="utf-8")
            events = list(iter_production_events(root))
            self.assertEqual([e["event_type"] for e in events], ["prediction.recorded", "prediction.validated"])
            self.assertTrue(all(e["source"] == "tianji-3k-readonly" for e in events))
            self.assertEqual(events_path.read_bytes(), before)
            self.assertNotIn("mode", events[0]["payload"])  # real predictions never become paper orders

    def test_since_filter_is_read_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "prod"
            day = root / "predictions" / "2026-10-15" / "2330"
            day.mkdir(parents=True)
            row = {"prediction_id":"p1", "trade_date":"2026-10-15", "symbol":"2330", "event_type":"INTRADAY_3K_PREDICTION", "created_at":"2026-10-15T09:01:00+08:00"}
            (day / "events.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
            self.assertEqual(list(iter_production_events(root, since="2026-10-16")), [])
            events = list(iter_production_events(root, since="2026-10-15"))
            self.assertEqual(len(events), 1)
            self.assertTrue((day / "events.jsonl").exists())
            self.assertEqual(sorted(p.name for p in (Path(tmp) / "prod").rglob("*" ) if p.is_file()), ["events.jsonl"])

if __name__ == "__main__":
    unittest.main()


def test_audit_pairs_validation_by_prediction_id_and_does_not_infer_ground_truth(tmp_path):
    from event_adapter.audit import build_production_audit
    day = tmp_path / 'predictions' / '2026-10-16' / '2330'
    day.mkdir(parents=True)
    path = day / 'events.jsonl'
    prediction = {'event_type':'INTRADAY_3K_PREDICTION','prediction_id':'p-2330','trade_date':'2026-10-16','symbol':'2330','created_at':'2026-10-16T09:15:00+08:00','context':{'name':'台積電','dynamic_candidate':True,'stage0_pass':False},'trigger_snapshot':{'current_price':100,'up_pct':4.2,'prediction_score':90,'signal_level':'EARLY'},'volume_snapshot':{'projected_ratio':2.4,'live_volume_ratio':1.8},'notification_status':'READY'}
    validation = {'event_type':'PREDICTION_VALIDATION','prediction_id':'p-2330','trade_date':'2026-10-16','symbol':'2330','ground_truth_available':False,'ground_truth_3k':None,'validation_status':'GROUND_TRUTH_UNAVAILABLE_AT_CUTOFF','validated_at':'2026-10-16T13:35:00+08:00'}
    notification = {'event_type':'NOTIFICATION','prediction_id':'p-2330','notification_status':'SENT','telegram_message_id':'123','sent_at':'2026-10-16T09:16:00+08:00'}
    path.write_text(json.dumps(prediction)+'\n'+json.dumps(validation)+'\n'+json.dumps(notification)+'\n', encoding='utf-8')
    before = path.read_bytes()
    audit = build_production_audit(tmp_path)
    assert audit['prediction_count'] == 1
    assert audit['validated_count'] == 1
    assert audit['ground_truth_available_count'] == 0
    assert audit['ground_truth_missing_count'] == 1
    row = audit['signals'][0]
    assert row['dynamic_candidate'] is True
    assert row['stage0_pass'] is False
    assert row['ground_truth_3k'] is None
    assert row['validation_status'] == 'GROUND_TRUTH_UNAVAILABLE_AT_CUTOFF'
    assert row['notification_gate_status'] == 'READY'
    assert row['notification_status'] == 'SENT'
    assert row['telegram_message_id'] == '123'
    assert path.read_bytes() == before
