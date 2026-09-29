from pathlib import Path
from tianji_3k.tools.stage0_production import OfficialReferenceResolver, ReferenceSnapshot, evaluate_stage0
from tianji_3k.tools.stage0_audit import CacheVolume


def resolver(tmp_path):
    r = OfficialReferenceResolver(tmp_path / "ref.json")
    r.snapshot = ReferenceSnapshot(
        "2026-09-21T00:00:00+00:00",
        {
            "twse_main": ["1101", "0050"],
            "twse_fund": ["0050"],
            "twse_warrant": ["123456"],
            "twse_suspend": ["1101"],
            "twse_disposal": [],
            "tpex_main": ["6488"],
            "tpex_warrant": [],
            "tpex_fund": [],
            "tpex_suspend": [],
            "tpex_disposal": [],
            "tpex_cmode": [],
        },
        {k: True for k in [
            "twse_main", "twse_fund", "twse_warrant", "twse_suspend", "twse_disposal",
            "tpex_main", "tpex_warrant", "tpex_fund", "tpex_suspend", "tpex_disposal", "tpex_cmode"
        ]}, {}, {}
    )
    return r


def vol(symbol="1101", lots=1200):
    return CacheVolume(symbol, "2026-09-18", lots * 1000, lots, "x.json")


def test_official_common_stock_pass(tmp_path):
    r = resolver(tmp_path)
    out = evaluate_stage0({"symbol": "1101", "name": "台泥", "market": "TWSE"}, vol(), r, 1000)
    assert out.product_type == "COMMON_STOCK"
    assert out.status == "SUSPENDED"
    assert out.final_stage0_pass is False


def test_official_fund_excluded(tmp_path):
    r = resolver(tmp_path)
    out = evaluate_stage0({"symbol": "0050", "name": "ETF", "market": "TWSE"}, vol("0050"), r, 1000)
    assert out.product_type == "ETF"
    assert out.first_exclusion == "PRODUCT_ETF"


def test_volume_unknown_never_becomes_zero(tmp_path):
    r = resolver(tmp_path)
    out = evaluate_stage0({"symbol": "6488", "name": "環球晶", "market": "TPEx"}, None, r, 1000)
    assert out.volume_lots is None
    assert out.first_exclusion == "VOLUME_UNKNOWN"


def test_low_volume_excluded(tmp_path):
    r = resolver(tmp_path)
    out = evaluate_stage0({"symbol": "6488", "name": "環球晶", "market": "TPEx"}, vol("6488", 999.9), r, 1000)
    assert out.first_exclusion == "VOLUME_LT_THRESHOLD"


def test_reference_failure_keeps_unknown(tmp_path):
    r = OfficialReferenceResolver(tmp_path / "ref.json")
    r.snapshot = ReferenceSnapshot("2026-09-21T00:00:00+00:00", {}, {}, {}, {})
    out = evaluate_stage0({"symbol": "6488", "name": "環球晶", "market": "TPEx"}, vol("6488"), r, 1000)
    assert out.product_type == "UNKNOWN"
    assert out.first_exclusion == "PRODUCT_TYPE_UNKNOWN"
