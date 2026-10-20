import unittest
from unittest.mock import patch
from datetime import datetime, timezone, timedelta
from tianji_radar import TaiwanMarketRadar

class RadarTests(unittest.TestCase):
    def test_discovery_gate_uses_lots_and_excludes_stale(self):
        r=TaiwanMarketRadar()
        r.universe={
            '2330':{'symbol':'2330','name':'台積電','market':'TWSE','exchange':'tse','security_type':'common_stock','previous_volume_lots':5000},
            '9999':{'symbol':'9999','name':'stale','market':'TWSE','exchange':'tse','security_type':'common_stock','previous_volume_lots':5000},
        }
        r.snapshot={
            '2330':{'symbol':'2330','name':'台積電','market':'TWSE','security_type':'common_stock','price':100,'up_pct':4,'volume_lots':1200,'today_open':98,'stale':False,'market_timestamp':'2026-10-16T10:00:00+08:00','data_age_seconds':2,'source':'TWSE MIS snapshot'},
            '9999':{'symbol':'9999','name':'stale','market':'TWSE','security_type':'common_stock','price':100,'up_pct':8,'volume_lots':800,'today_open':98,'stale':True,'market_timestamp':None,'data_age_seconds':9999,'source':'TWSE MIS snapshot'},
        }
        now=datetime(2026,10,16,10,0,tzinfo=timezone(timedelta(hours=8)))
        got=r._discover(now)
        self.assertEqual([x['symbol'] for x in got],['2330'])
        self.assertEqual(got[0]['status'],'DYNAMIC_CANDIDATE_NOT_3K_PASS')

    def test_empty_or_failed_snapshot_does_not_fake_prices(self):
        r=TaiwanMarketRadar()
        with patch('tianji_radar._get_json', side_effect=RuntimeError('offline')):
            out=r.scan()
        self.assertTrue(out['last_error'])
        self.assertEqual(out['market_snapshot'],[])

if __name__=='__main__': unittest.main()
