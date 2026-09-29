import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tianji_3k.tools.stage0_audit import audit_rows, load_cache_volumes, summary


def test_stage0_order_and_1000_threshold(tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "a.json").write_text(json.dumps([
        {"date":"2026-09-18","stock_id":"1001","Trading_Volume":900000},
        {"date":"2026-09-18","stock_id":"1002","Trading_Volume":1200000},
        {"date":"2026-09-18","stock_id":"1003","Trading_Volume":2000000},
        {"date":"2026-09-18","stock_id":"1004","Trading_Volume":3000000},
    ]), encoding="utf-8")
    vols, _ = load_cache_volumes(cache)
    universe = [
        {"symbol":"1001","name":"A","market":"TWSE","security_type":"common_stock","is_disposal":False,"is_suspended":False},
        {"symbol":"1002","name":"B","market":"TWSE","security_type":"etf","is_disposal":False,"is_suspended":False},
        {"symbol":"1003","name":"C","market":"TWSE","security_type":"common_stock","is_disposal":True,"is_suspended":False},
        {"symbol":"1004","name":"D","market":"TWSE","security_type":"common_stock","is_disposal":False,"is_suspended":False},
    ]
    rows = audit_rows(universe, vols, 1000, trust_universe_fields=True)
    assert [r.first_exclusion for r in rows] == ["YESTERDAY_VOLUME", "PRODUCT_TYPE", "STATUS", ""]
    assert summary(rows, 1000)["stage0_pass"] == 1


def test_latest_cache_row_wins(tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "a.json").write_text(json.dumps([
        {"date":"2026-09-17","stock_id":"1234","Trading_Volume":500000},
        {"date":"2026-09-18","stock_id":"1234","Trading_Volume":1500000},
    ]), encoding="utf-8")
    vols, _ = load_cache_volumes(cache)
    assert vols["1234"].trade_date == "2026-09-18"
    assert vols["1234"].volume_lots == 1500


def test_missing_cache_is_unknown_not_zero(tmp_path):
    universe = [{
        "symbol": "1234", "name": "A", "market": "TWSE",
        "security_type": "common_stock", "is_disposal": False, "is_suspended": False,
        "previous_volume_lots": 0.0,
    }]
    rows = audit_rows(universe, {}, 1000, trust_universe_fields=True)
    assert rows[0].volume_lots is None
    assert rows[0].volume_source == "unavailable"
    assert rows[0].first_exclusion == "DATA_QUALITY"


def test_product_and_status_unknown_are_not_pass():
    universe = [{"symbol": "1234", "name": "A", "market": "TWSE"}]
    rows = audit_rows(universe, {}, 1000, trust_universe_fields=False)
    assert rows[0].product_type == "UNKNOWN"
    assert rows[0].status == "UNKNOWN"
    assert rows[0].first_exclusion == "PRODUCT_TYPE_UNKNOWN"
    assert rows[0].final_stage0_pass is False


def test_custom_volume_threshold_is_used():
    universe = [{
        "symbol": "1234", "name": "A", "market": "TWSE",
        "security_type": "common_stock", "is_disposal": False, "is_suspended": False,
    }]
    cache = {"1234": type("V", (), {"trade_date":"2026-09-18", "volume_shares":1500000, "volume_lots":1500})()}
    rows = audit_rows(universe, cache, 2000, trust_universe_fields=True)
    assert rows[0].first_exclusion == "YESTERDAY_VOLUME"
    assert summary(rows, 2000)["volume_lt_threshold"] == 1
