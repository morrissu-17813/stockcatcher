import sys, unittest
from pathlib import Path
from datetime import datetime, timezone, timedelta
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from trade_confirmation import projected_volume, RadarSnapshot, RadarStateMachine, FugleFiveMinuteProvider

class TradeConfirmationUnitTests(unittest.TestCase):
    def test_projection_fails_closed_before_five_minutes(self):
        t=datetime(2026,10,16,9,2,tzinfo=timezone(timedelta(hours=8)))
        out=projected_volume(10000,t,1000)
        self.assertFalse(out['ready']); self.assertFalse(out['passed']); self.assertIsNone(out['projected_ratio'])
    def test_projection_requires_at_least_1_5x(self):
        t=datetime(2026,10,16,10,30,tzinfo=timezone(timedelta(hours=8)))
        out=projected_volume(900,t,2000)
        self.assertFalse(out['passed'])
        passed=projected_volume(3000,t,2000)
        self.assertTrue(passed['passed'])
    def test_state_machine_requires_two_distinct_data_identities(self):
        sm=RadarStateMachine()
        a=RadarSnapshot('2330','id-1','same',106,100,101,6)
        b=RadarSnapshot('2330','id-2','same',106,100,101,6)
        self.assertFalse(sm.evaluate(a,100)[0])
        self.assertEqual(sm.evaluate(b,100)[1],'DUPLICATE_SNAPSHOT')
        c=RadarSnapshot('2330','id-3','new',106,100,101,6)
        self.assertTrue(sm.evaluate(c,100)[0])
    def test_fugle_five_minute_requires_key(self):
        with self.assertRaisesRegex(RuntimeError,'FUGLE_API_KEY_NOT_CONFIGURED'):
            FugleFiveMinuteProvider(api_key='').bars('2330')

if __name__=='__main__': unittest.main()
