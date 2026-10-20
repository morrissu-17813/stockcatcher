import json, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from event_adapter.reader import read_events

class EventReaderTests(unittest.TestCase):
    def test_reads_only_allowed_well_formed_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "events.jsonl"
            rows = [
                {"event_id":"1","event_type":"signal.created","occurred_at":"2026-10-16T09:00:00+08:00"},
                {"event_id":"2","event_type":"unknown.event","occurred_at":"2026-10-16T09:01:00+08:00"},
            ]
            p.write_text("\n".join(json.dumps(x) for x in rows) + "\n{bad json\n", encoding="utf-8")
            events = list(read_events(p))
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["event_id"], "1")

if __name__ == "__main__":
    unittest.main()
