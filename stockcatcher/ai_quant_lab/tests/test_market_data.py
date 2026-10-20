import unittest
from unittest.mock import patch
from market_data import FugleChartClient, MarketDataError, build_market_client

class FakeHttp:
    def __init__(self, responses): self.responses=list(responses); self.calls=[]
    def get(self,url,headers=None): self.calls.append((url,headers)); return self.responses.pop(0)

class MarketDataTests(unittest.TestCase):
    def test_fugle_maps_intraday_candles_and_quote(self):
        candles={'symbol':'2330','data':[
            {'date':'2026-10-16T09:00:00.000+08:00','open':100,'high':102,'low':99,'close':101,'volume':500},
            {'date':'2026-10-16T09:01:00.000+08:00','open':101,'high':103,'low':100,'close':102,'volume':600},
        ]}
        quote={'symbol':'2330','name':'台積電','lastPrice':102,'previousClose':98}
        client=FugleChartClient(api_key='test-secret'); client.http=FakeHttp([candles,quote])
        with patch('market_data.datetime') as dt:
            # Keep timestamp age deterministic and ensure schema normalization is the test target.
            dt.fromisoformat.return_value=None
            result=client.fetch('2330.TW')
        self.assertEqual(result['symbol'],'2330'); self.assertEqual(result['price'],102)
        self.assertAlmostEqual(result['change_pct'],(102/98-1)*100)
        self.assertEqual(result['source'],'Fugle Market Data API')
        self.assertEqual(len(result['candles']),2)
        self.assertTrue(all(call[1]['X-API-KEY']=='test-secret' for call in client.http.calls))
    def test_fugle_requires_key(self):
        with patch.dict('os.environ',{},clear=True):
            with self.assertRaises(MarketDataError): FugleChartClient(api_key='').fetch('2330')
    def test_provider_prefers_fugle_when_key_present(self):
        with patch.dict('os.environ',{'FUGLE_API_KEY':'test-key'},clear=True):
            self.assertIsInstance(build_market_client(),FugleChartClient)
    def test_fugle_empty_candles_fails_closed(self):
        client=FugleChartClient(api_key='test-key'); client.http=FakeHttp([{'data':[]}])
        with self.assertRaises(MarketDataError): client.fetch('2330')

if __name__=='__main__': unittest.main()
