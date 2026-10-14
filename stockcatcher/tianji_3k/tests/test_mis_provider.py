from types import SimpleNamespace

from tianji_3k.data.mis import MISProvider


class FakeSession:
    def __init__(self, payload):
        self.payload = payload

    def get(self, *args, **kwargs):
        return SimpleNamespace(json=lambda: self.payload)


def _provider(item):
    provider = MISProvider({"6668": {"name": "中揚光"}}, lambda _: "tse")
    provider.initialized = True
    provider.session = FakeSession({"msgArray": [item]})
    return provider


def test_mis_skips_missing_last_price_instead_of_using_previous_close():
    provider = _provider({"c": "6668", "y": "51.10", "z": "-", "o": "51.10", "v": "100"})
    assert provider.fetch_batch() == {}


def test_mis_keeps_valid_last_traded_price():
    provider = _provider({"c": "6668", "y": "51.10", "z": "56.20", "o": "51.10", "v": "7855", "t": "11:38:52", "tv": "4", "d": "20261012"})
    result = provider.fetch_batch()["6668"]
    assert result["current_price"] == 56.20
    assert result["up_pct"] > 9.9
    assert result["is_traded"] is True


def test_mis_quote_timestamp_parses_exchange_time_and_detects_old_quote():
    from datetime import datetime, timezone, timedelta

    now = datetime(2026, 10, 13, 13, 13, 39, tzinfo=timezone(timedelta(hours=8)))
    quote = MISProvider._quote_timestamp(
        {"d": "20261013", "t": "13:11:55"}, now=now
    )
    assert quote is not None
    assert (now - quote).total_seconds() == 104


def test_mis_parallel_batches_merge_results_without_dropping_successes(monkeypatch):
    import tianji_3k.data.mis as mis_module

    monkeypatch.setattr(mis_module, "MIS_BATCH_SIZE", 1)
    provider = MISProvider({"1101": {}, "1102": {}, "1103": {}}, lambda _: "tse")

    def fake_fetch_chunk(batch, worker_session=False):
        sid = batch[0]
        return {sid: {"symbol": sid}}, False

    provider._fetch_chunk = fake_fetch_chunk
    result = provider.fetch_batch()
    assert set(result) == {"1101", "1102", "1103"}
    assert provider.last_fetch_stats["batches"] == 3
    assert provider.last_fetch_stats["returned_symbols"] == 3
    assert provider.last_fetch_stats["failed_batches"] == 0


def test_mis_provider_reports_raw_items_and_parse_rejections():
    provider = MISProvider({"1101": {}, "1102": {}, "1103": {}}, lambda _: "tse")
    provider.initialized = True
    provider.session = FakeSession({"msgArray": [
        {"c": "1101", "y": "20", "z": "21", "o": "20", "v": "100", "t": "10:00:00", "d": "20261014"},
        {"c": "1102", "y": "20", "z": "-", "o": "20", "v": "100", "t": "10:00:00", "d": "20261014"},
        {"c": "1103", "y": "-", "z": "21", "o": "20", "v": "100", "t": "10:00:00", "d": "20261014"},
    ]})
    result = provider.fetch_batch()
    assert set(result) == {"1101"}
    stats = provider.last_fetch_stats
    assert stats["raw_items"] == 3
    assert stats["returned_symbols"] == 1
    assert stats["missing_last_price"] == 1
    assert stats["invalid_previous_close"] == 1
    assert stats["failed_batches"] == 0
    assert stats["batch_stats"][0]["raw_items"] == 3
    assert stats["batch_stats"][0]["parsed"] == 1
