from datetime import datetime

from tianji_3k.core.dynamic_discovery import DynamicDiscoveryConfig, discovery_candidates


def test_dynamic_discovery_is_market_wide_and_ranked():
    raw = {
        "1111": {"up_pct": 5.0, "current_price": 105, "today_open": 100, "cumulative_volume_lots": 400},
        "2222": {"up_pct": 4.0, "current_price": 104, "today_open": 100, "cumulative_volume_lots": 1000},
        "3333": {"up_pct": 2.0, "current_price": 102, "today_open": 100, "cumulative_volume_lots": 2000},
    }
    universe = {
        "1111": {"previous_volume_lots": 1000, "name": "A", "market": "TWSE"},
        "2222": {"previous_volume_lots": 1000, "name": "B", "market": "TPEx"},
        "3333": {"previous_volume_lots": 1000, "name": "C", "market": "TWSE"},
    }
    rows = discovery_candidates(
        raw,
        universe,
        now=datetime(2026, 10, 2, 10, 0),
        config=DynamicDiscoveryConfig(min_current_volume_lots=300, min_volume_pace_ratio=0.8),
    )
    assert [x["symbol"] for x in rows] == ["1111", "2222"]
    assert rows[0]["discovery_source"] == "MIS_MARKET_WIDE"


def test_dynamic_discovery_never_reenriches_active_or_exhausted_symbols():
    raw = {
        "1111": {"up_pct": 5.0, "current_price": 105, "today_open": 100, "cumulative_volume_lots": 1000},
        "2222": {"up_pct": 5.0, "current_price": 105, "today_open": 100, "cumulative_volume_lots": 1000},
    }
    universe = {
        "1111": {"previous_volume_lots": 1000},
        "2222": {"previous_volume_lots": 1000},
    }
    rows = discovery_candidates(
        raw,
        universe,
        existing={"1111"},
        attempts={"2222": 3},
        now=datetime(2026, 10, 2, 10, 0),
    )
    assert rows == []


def test_dynamic_discovery_uses_explicit_mis_lots_without_dividing_twice():
    raw = {"1111": {"up_pct": 5.0, "current_price": 105, "today_open": 100, "cumulative_volume_lots": 400}}
    universe = {"1111": {"previous_volume_lots": 1000}}
    rows = discovery_candidates(raw, universe, now=datetime(2026, 10, 2, 10, 0))
    assert rows and rows[0]["current_volume_lots"] == 400
