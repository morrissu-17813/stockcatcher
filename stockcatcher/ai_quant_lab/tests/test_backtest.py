import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backtest import run_backtest


def test_backtest_rejects_insufficient_history():
    assert run_backtest('2330', [])['ok'] is False


def test_backtest_returns_auditable_report_for_daily_bars():
    bars=[]
    price=100.0
    from datetime import date, timedelta
    day=date(2025,1,1)
    for i in range(120):
        price += 0.15 if i % 4 else -0.08
        bars.append({'date':(day+timedelta(days=i)).isoformat(),'open':price*.995,'high':price*1.01,'low':price*.99,'close':price,'volume':2_000_000})
    report=run_backtest('2330',bars)
    assert report['ok'] is True
    assert report['bars'] >= 30
    assert 'assumptions' in report
    assert 'trade_rows' in report
    assert '週 KD' in report['strategy']
