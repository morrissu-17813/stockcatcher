from types import SimpleNamespace

import pytest

from tianji_3k.data.fugle import FugleAPIError, FugleProvider


def test_fugle_401_is_structured_error(monkeypatch):
    provider = FugleProvider("valid-looking-key")

    def fake_get(*args, **kwargs):
        response = SimpleNamespace(status_code=401)
        err = __import__("requests").HTTPError("401 unauthorized", response=response)
        raise err

    monkeypatch.setattr("tianji_3k.data.fugle.requests.get", fake_get)
    with pytest.raises(FugleAPIError) as exc:
        provider.get_5m_bars("2330")
    assert exc.value.status_code == 401
    assert exc.value.symbol == "2330"


def test_fugle_health_check_accepts_http_success_without_23_bars(monkeypatch):
    provider = FugleProvider("key")
    monkeypatch.setattr(provider, "get_5m_bars", lambda symbol: [{"date": "x"}] * 3)
    result = provider.check_5m_access("2330")
    assert result == {"ok": True, "status": "OK", "symbol": "2330", "bars": 3}
