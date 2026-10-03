import pandas as pd

from tianji_3k.core.dynamic_candidate import evaluate_dynamic_history
from tianji_3k.data.fugle import FugleProvider


def _bars(n=70):
    dates = pd.date_range("2026-06-01", periods=n, freq="B")
    rows = []
    for i, d in enumerate(dates):
        close = 100 + i * 0.5
        rows.append({
            "date": d,
            "open": close - 0.5,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": 2_000_000,
            "volume_lots": 2000,
        })
    return pd.DataFrame(rows)


def test_dynamic_history_builds_intraday_context():
    result = evaluate_dynamic_history("1234", _bars(), name="測試", market="TWSE", trade_date="2026-10-02")
    assert result.eligible
    assert result.context["breakout_level"] > 0
    assert result.context["vma5_lots"] >= 1000
    assert result.context["stage1_pass"] is True
    assert result.context["stage0_pass"] is False
    assert result.context["dynamic_discovery_pass"] is True


def test_fugle_micro_breakout_uses_completed_bars(monkeypatch):
    provider = FugleProvider("key")
    bars = []
    for i in range(23):
        high = 100 + i * 0.1
        bars.append({
            "date": f"2026-10-02T09:{i:02d}:00+08:00",
            "open": high - 0.2,
            "high": high,
            "low": high - 0.5,
            "close": high - 0.1,
            "volume": 1000,
        })
    bars[-3]["high"] = 100.0
    bars[-2]["high"] = 100.5
    bars[-3]["close"] = 100.2
    bars[-2]["close"] = 100.4
    bars[-1]["close"] = 101.0
    bars[-1]["high"] = 101.2
    bars[-1]["volume"] = 1500
    monkeypatch.setattr(provider, "get_5m_bars", lambda symbol, limit=200: bars)
    signal = provider.evaluate_3k_micro_breakout("1234")
    assert signal is not None
    assert signal["breakout_price"] == 100.5
    assert signal["volume_ratio"] >= 1.2
