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
