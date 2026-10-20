from unittest.mock import patch
import benchmarks

def test_benchmark_failures_are_explicit_and_not_faked():
    benchmarks._CACHE.update(at=0.0, payload=None)
    with patch.object(benchmarks, '_quote', side_effect=RuntimeError('provider down')), \
         patch.object(benchmarks, '_taifex_sxf_quote', side_effect=RuntimeError('TAIFEX provider down')):
        result = benchmarks.get_benchmarks(force=True)
    assert len(result['items']) == 7
    assert all(item['ok'] is False and item['value'] is None for item in result['items'])
    assert len(result['errors']) == 7
    assert all(item['history'] == [] for item in result['items'])

def test_benchmark_success_shape():
    benchmarks._CACHE.update(at=0.0, payload=None)
    with patch.object(benchmarks, '_quote', return_value=(123.4, 0.25, 'test source', 'TWD', [120.0, 121.0, 123.4])), \
         patch.object(benchmarks, '_taifex_sxf_quote', return_value=(456.7, -0.5, 'TAIFEX daily report', 'TWD', [456.7])):
        result = benchmarks.get_benchmarks(force=True)
    assert len(result['items']) == 7
    assert all(item['ok'] is True and item['value'] is not None for item in result['items'])
    assert result['items'][0]['source'] == 'test source'
    assert result['items'][0]['history'] == [120.0, 121.0, 123.4]
    assert result['items'][-1]['source'] == 'TAIFEX daily report'

def test_taifex_sxf_daily_quote_is_labeled_as_daily_report():
    import json
    from unittest.mock import MagicMock
    response = MagicMock()
    response.__enter__.return_value.read.return_value = json.dumps([
        {"Date": "2026/10/16", "Contract": "SXF", "ContractMonth(Week)": "202612", "Last": "12345", "Change(%)": "▲0.66%"},
        {"Date": "2026/10/16", "Contract": "TX", "ContractMonth(Week)": "202612", "Last": "50000"},
    ]).encode()
    with patch.object(benchmarks.urllib.request, 'urlopen', return_value=response):
        value, change, source, currency, history = benchmarks._taifex_sxf_quote()
    assert value == 12345
    assert change == 0.66
    assert '非逐筆即時' in source
    assert currency == 'TWD'
    assert history == [12345]
