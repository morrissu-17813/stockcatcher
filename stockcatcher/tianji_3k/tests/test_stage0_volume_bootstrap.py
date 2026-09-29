import json
from pathlib import Path

from tianji_3k.data.stage0_volume_bootstrap import bootstrap


class Resp:
    def __init__(self, payload):
        self.payload = payload
    def raise_for_status(self):
        pass
    def json(self):
        return self.payload


class Session:
    def __init__(self):
        self.calls = []
    def get(self, url, **kwargs):
        self.calls.append(url)
        if "twse" in url:
            return Resp([{"Date": "1150924", "Code": "1101", "TradeVolume": "1234000"}])
        return Resp([{"Date": "1150924", "SecuritiesCompanyCode": "6488", "TradingShares": "2345000"}])


def test_bootstrap_writes_both_market_volume_rows(tmp_path):
    s = Session()
    result = bootstrap(tmp_path, "2026-09-24", session=s)
    assert result["status"] == "REFRESHED"
    assert result["rows"] == 2
    assert result["requests"] == 2
    payload = json.loads((tmp_path / "stage0_volume_2026-09-24.json").read_text())
    assert {r["stock_id"] for r in payload} == {"1101", "6488"}
    assert {r["volume_lots"] for r in payload} == {1234.0, 2345.0}


def test_bootstrap_cache_hit_does_not_request_again(tmp_path):
    p = tmp_path / "stage0_volume_2026-09-24.json"
    p.write_text(json.dumps([{"stock_id":"1101","date":"2026-09-24","volume_shares":1000}]))
    s = Session()
    result = bootstrap(tmp_path, "2026-09-24", session=s)
    assert result["status"] == "CACHE_HIT"
    assert result["requests"] == 0
    assert not s.calls


def test_bootstrap_fails_closed_when_one_market_missing(tmp_path):
    class Partial(Session):
        def get(self, url, **kwargs):
            self.calls.append(url)
            if "twse" in url:
                return Resp([{"Date": "1150924", "Code": "1101", "TradeVolume": "1234000"}])
            return Resp([])
    result = bootstrap(tmp_path, "2026-09-24", session=Partial())
    assert result["status"] == "FAILED"
    assert result["rows"] == 1
