import pandas as pd

from tianji_3k.data.cache_first import CacheFirstDailyProvider


class Calendar:
    def expected_trading_days(self, start, end):
        return list(pd.bdate_range(start, end).date)


def row(d, close=100):
    return {"date": d, "open": close, "high": close + 1, "low": close - 1, "close": close, "volume": 100000}


def test_symbol_specific_suspension_does_not_fail_history_backfill(tmp_path):
    p = CacheFirstDailyProvider("", cache_dir=tmp_path, calendar=Calendar())
    # 3591 艾笛森 was suspended 2026-09-10..2026-09-18 for capital-reduction
    # exchange; those are market trading days but legitimately have no stock bars.
    suspended = {
        "2026-09-10", "2026-09-11", "2026-09-14", "2026-09-15",
        "2026-09-16", "2026-09-17", "2026-09-18",
    }
    traded = [
        d.strftime("%Y-%m-%d")
        for d in pd.bdate_range("2026-09-01", "2026-09-24")
        if d.strftime("%Y-%m-%d") not in suspended
    ]
    p.fallback.get_daily = lambda symbol, start, end: pd.DataFrame([row(d) for d in traded])
    out = p.get_daily("3591", "2026-09-01", "2026-09-24")
    assert len(out) == len(traded)
    assert "2026-09-18" not in out.date.astype(str).tolist()
