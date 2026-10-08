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


def _make_micro_bars(*, structure: bool, volume_ratio: float):
    bars = []
    for i in range(23):
        base = 100 + i * 0.1
        bars.append({
            "date": f"2026-10-02T09:{i:02d}:00+08:00",
            "open": base - 0.1,
            "high": base,
            "low": base - 0.5,
            "close": base - 0.05,
            "volume": 1000,
        })
    bars[-3]["high"] = 100.0
    bars[-2]["high"] = 100.5
    bars[-1]["close"] = 100.6 if structure else 100.4
    bars[-1]["high"] = 100.8
    bars[-1]["volume"] = 1000 * volume_ratio
    return bars


def test_fugle_micro_breakout_accepts_structure_without_volume(monkeypatch):
    provider = FugleProvider("key")
    bars = _make_micro_bars(structure=True, volume_ratio=0.9)
    monkeypatch.setattr(provider, "get_5m_bars", lambda symbol, limit=200: bars)
    signal = provider.evaluate_3k_micro_breakout("1234")
    assert signal is not None
    assert signal["structure_pass"] is True
    assert signal["volume_pass"] is False
    assert signal["micro_pass"] is True


def test_fugle_micro_breakout_accepts_volume_without_structure(monkeypatch):
    provider = FugleProvider("key")
    bars = _make_micro_bars(structure=False, volume_ratio=1.10)
    monkeypatch.setattr(provider, "get_5m_bars", lambda symbol, limit=200: bars)
    signal = provider.evaluate_3k_micro_breakout("1234")
    assert signal is not None
    assert signal["structure_pass"] is False
    assert signal["volume_pass"] is True
    assert signal["micro_pass"] is True
