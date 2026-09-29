import json
from pathlib import Path

import pandas as pd

from tianji_3k.data.daily_refresh import DailyDataRefreshManager
from tianji_3k.data.official_daily import OfficialDailySnapshotProvider
from tianji_3k.data.finmind_budget import FinMindRequestBudget


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload
    def raise_for_status(self):
        return None
    def json(self):
        return self.payload


class FakeSession:
    def __init__(self):
        self.headers = {}
        self.calls = []
    def get(self, url, timeout):
        self.calls.append(url)
        if "twse" in url:
            return FakeResponse([{
                "Code": "1101", "OpeningPrice": "30", "HighestPrice": "31",
                "LowestPrice": "29", "ClosingPrice": "30.5", "TradeVolume": "1234000"
            }])
        return FakeResponse([{
            "SecuritiesCompanyCode": "6409", "OpeningPrice": "100", "HighestPrice": "105",
            "LowestPrice": "99", "ClosingPrice": "104", "TradingShares": "2345000"
        }])


def test_official_provider_is_two_market_requests():
    session = FakeSession()
    p = OfficialDailySnapshotProvider(session=session)
    result, frame = p.fetch_result("2026-09-24")
    assert result.status == "READY"
    assert result.twse_rows == 1
    assert result.tpex_rows == 1
    assert result.total_rows == 2
    assert len(session.calls) == 2
    assert set(frame["stock_id"]) == {"1101", "6409"}


def test_official_refresh_populates_cache_without_finmind(tmp_path):
    manager = DailyDataRefreshManager(
        cache_dir=tmp_path / "daily",
        audit_path=tmp_path / "freshness.json",
        token="",
        budget=FinMindRequestBudget(limit=580),
    )
    fake = FakeSession()
    manager.official_daily = OfficialDailySnapshotProvider(session=fake)

    out = manager.refresh_official_daily("2026-09-24")
    assert out["status"] == "READY"
    assert out["rows_written"] == 2
    assert manager.budget.snapshot()["used"] == 0

    files = sorted((tmp_path / "daily").glob("TaiwanStockPrice_*.json"))
    assert len(files) == 2

    # The next read is a pure cache hit and must not reserve FinMind budget.
    manager.provider.calendar = None
    df = manager.provider.get_daily("1101", "2026-09-24", "2026-09-24")
    assert len(df) == 1
    assert manager.budget.snapshot()["used"] == 0
