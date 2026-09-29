"""
Tianji 3K Cache First diagnostic probe.

Purpose:
    Verify exactly what date range CacheFirstDailyProvider asks FinMind
    to fetch for a stock that already has local cache.

Default:
    symbol = 6409
    requested range = 2026-03-25 ~ 2026-09-21

The script monkey-patches the provider's FinMind fallback with a recorder.
Therefore it DOES NOT call FinMind and DOES NOT consume API quota.

Usage:
    python cache_probe.py

Optional:
    $env:TIANJI_PROBE_SYMBOL="6409"
    python cache_probe.py
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

from tianji_3k.data.cache_first import CacheFirstDailyProvider


SYMBOL = os.getenv("TIANJI_PROBE_SYMBOL", "6409")
REQUESTED_START = os.getenv("TIANJI_PROBE_START", "2026-03-25")
REQUESTED_END = os.getenv("TIANJI_PROBE_END", "2026-09-21")


def date_range(df: pd.DataFrame) -> str:
    if df is None or df.empty or "date" not in df.columns:
        return "EMPTY"
    dates = pd.to_datetime(df["date"], errors="coerce").dropna()
    if dates.empty:
        return "EMPTY"
    return f"{dates.min().date()} ~ {dates.max().date()}"


class RecorderFallback:
    """Fake FinMind provider: records calls and returns deterministic rows."""

    def __init__(self):
        self.calls = []

    def get_daily(self, symbol: str, start: str, end: str) -> pd.DataFrame:
        self.calls.append(
            {
                "symbol": str(symbol),
                "start": str(start),
                "end": str(end),
            }
        )

        start_ts = pd.Timestamp(start)
        end_ts = pd.Timestamp(end)

        # Return one deterministic row for every calendar day in the requested
        # interval. This is only for testing the cache merge path; no network.
        dates = pd.date_range(start_ts, end_ts, freq="D")

        if len(dates) == 0:
            return pd.DataFrame()

        return pd.DataFrame(
            {
                "date": dates,
                "stock_id": [str(symbol)] * len(dates),
                "Trading_Volume": [1000000] * len(dates),
                "Trading_money": [100000000] * len(dates),
                "open": [100.0] * len(dates),
                "max": [101.0] * len(dates),
                "min": [99.0] * len(dates),
                "close": [100.5] * len(dates),
                "spread": [0.5] * len(dates),
                "Trading_turnover": [1000] * len(dates),
            }
        )


def main() -> int:
    print("=" * 76)
    print("Tianji 3K Cache First Diagnostic Probe")
    print("=" * 76)
    print(f"SYMBOL          : {SYMBOL}")
    print(f"REQUESTED RANGE : {REQUESTED_START} ~ {REQUESTED_END}")
    print()

    # Token is irrelevant because the fallback is replaced by a recorder.
    provider = CacheFirstDailyProvider(
        token="CACHE_PROBE_NO_NETWORK",
    )

    recorder = RecorderFallback()
    provider.fallback = recorder

    # Locate candidate cache files first, without modifying anything.
    candidates = provider._candidate_files(SYMBOL)

    print(f"CACHE DIR       : {provider.cache_dir}")
    print(f"CANDIDATE FILES : {len(candidates)}")
    print()

    if not candidates:
        print("WARNING: 找不到此股票的 cache。")
        print("這次測試將驗證 CACHE_MISS 行為，但不會呼叫 FinMind。")
    else:
        print("CACHE FILES:")
        for path in candidates[:10]:
            try:
                df = provider._read_file(path)
                print(f"  - {path.name}")
                print(f"    range={date_range(df)}, rows={len(df)}")
            except Exception as exc:
                print(f"  - {path.name}")
                print(f"    INVALID: {type(exc).__name__}: {exc}")

    print()
    print("-" * 76)
    print("RUNNING get_daily() — NETWORK DISABLED")
    print("-" * 76)

    try:
        result = provider.get_daily(
            SYMBOL,
            REQUESTED_START,
            REQUESTED_END,
        )
    except Exception as exc:
        print(f"GET_DAILY ERROR: {type(exc).__name__}: {exc}")
        return 1

    print()
    print("=" * 76)
    print("RESULT")
    print("=" * 76)

    print(f"RESULT RANGE    : {date_range(result)}")
    print(f"RESULT ROWS     : {len(result)}")
    print(f"STATS           : {provider.stats()}")

    print()
    print("FINMIND CALLS RECORDED (NO NETWORK)")
    print("-" * 76)

    if not recorder.calls:
        print("NONE")
    else:
        for i, call in enumerate(recorder.calls, start=1):
            print(
                f"{i}. {call['symbol']} "
                f"{call['start']} ~ {call['end']}"
            )

    print()
    print("=" * 76)
    print("DIAGNOSIS")
    print("=" * 76)

    if not recorder.calls:
        print("CACHE HIT：沒有任何 FinMind fallback。")
    elif len(recorder.calls) == 1:
        call = recorder.calls[0]
        if (
            call["start"] == REQUESTED_END
            and call["end"] == REQUESTED_END
        ):
            print("PASS：只要求缺少的尾端日期。")
            print(
                f"期待的增量區間："
                f"{REQUESTED_END} ~ {REQUESTED_END}"
            )
        else:
            print("WARNING：有 fallback，但不是只補最後缺少的一天。")
            print(
                f"實際要求：{call['start']} ~ {call['end']}"
            )
    else:
        print(f"WARNING：產生了 {len(recorder.calls)} 次 fallback。")
        for call in recorder.calls:
            print(
                f"  {call['start']} ~ {call['end']}"
            )

    print()
    print("注意：本 Probe 不會連線 FinMind，因此不會消耗 API quota。")
    print("若測試通過，再讓正式 runner 執行才有意義。")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
