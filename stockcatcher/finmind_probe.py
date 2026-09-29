"""
FinMind single-request diagnostic probe for Tianji 3K.

Usage:
    python finmind_probe.py

This script intentionally does NOT print the FinMind token.
It tests progressively larger date ranges for one stock and reports
HTTP status / response classification.
"""

from __future__ import annotations

import os
import sys
import time
from datetime import date
from pathlib import Path

import requests
from dotenv import load_dotenv


# Load the existing StockCatcher root .env.
HERE = Path(__file__).resolve()
CANDIDATES = [
    HERE.parent / ".env",
    HERE.parent / "stockcatcher" / ".env",
    Path.cwd() / ".env",
]

for p in CANDIDATES:
    if p.exists():
        load_dotenv(p, override=False)

TOKEN = (
    os.getenv("FINMIND_TOKEN")
    or os.getenv("FinMind_TOKEN")
    or os.getenv("FINMIND_API_TOKEN")
    or os.getenv("TIANJI_FINMIND_TOKEN")
)

BASE_URL = "https://api.finmindtrade.com/api/v4/data"
SYMBOL = os.getenv("FINMIND_PROBE_SYMBOL", "6409")

# Tests are deliberately small first.
TESTS = [
    ("1_day_past", "2026-09-18", "2026-09-18"),
    ("5_days", "2026-09-14", "2026-09-18"),
    ("20_days", "2026-08-24", "2026-09-18"),
    ("today_only", "2026-09-21", "2026-09-21"),
]


def classify(status: int, body: str) -> str:
    lower = body.lower()

    if status == 200:
        return "SUCCESS"
    if status == 402:
        if "upper limit" in lower:
            return "HTTP_402_UPPER_LIMIT"
        return "HTTP_402_PAYMENT_REQUIRED"
    if status == 401:
        return "HTTP_401_UNAUTHORIZED"
    if status == 403:
        return "HTTP_403_FORBIDDEN"
    if status == 429:
        return "HTTP_429_RATE_LIMIT"
    if status >= 500:
        return f"HTTP_{status}_SERVER_ERROR"
    return f"HTTP_{status}"


def safe_body(response: requests.Response) -> str:
    """Return a short body without ever exposing token-like strings."""
    text = response.text.replace("\n", " ").strip()
    if len(text) > 500:
        text = text[:500] + "..."
    return text


def run_one(name: str, start: str, end: str) -> bool:
    params = {
        "dataset": "TaiwanStockPrice",
        "start_date": start,
        "end_date": end,
        "data_id": SYMBOL,
    }

    if TOKEN:
        params["token"] = TOKEN

    print()
    print("=" * 72)
    print(f"TEST       : {name}")
    print(f"SYMBOL     : {SYMBOL}")
    print(f"DATE       : {start} ~ {end}")
    print(f"TOKEN      : {'FOUND' if TOKEN else 'NOT FOUND'}")
    print("-" * 72)

    started = time.perf_counter()

    try:
        response = requests.get(
            BASE_URL,
            params=params,
            timeout=20,
        )
        elapsed = time.perf_counter() - started

        result = classify(response.status_code, response.text)

        print(f"HTTP STATUS : {response.status_code}")
        print(f"RESULT      : {result}")
        print(f"ELAPSED     : {elapsed:.2f}s")

        # Do not print response headers because some services may expose
        # request IDs or sensitive metadata there.
        body = safe_body(response)

        if response.status_code == 200:
            try:
                payload = response.json()
                data = payload.get("data", [])
                print(f"ROWS        : {len(data)}")

                if data:
                    first = data[0]
                    last = data[-1]
                    print(f"FIRST DATE  : {first.get('date', 'N/A')}")
                    print(f"LAST DATE   : {last.get('date', 'N/A')}")
                    print("SAMPLE      : SUCCESS (row content omitted)")
                else:
                    print("ROWS        : 0")
                    print("NOTE        : HTTP 200 but no rows returned.")

            except Exception as exc:
                print(f"JSON PARSE  : FAILED ({type(exc).__name__})")
                print(f"BODY        : {body}")
            return True

        print(f"BODY        : {body}")
        return False

    except requests.RequestException as exc:
        elapsed = time.perf_counter() - started
        print(f"RESULT      : REQUEST_EXCEPTION")
        print(f"ELAPSED     : {elapsed:.2f}s")
        print(f"ERROR       : {type(exc).__name__}: {exc}")
        return False


def main() -> int:
    print("=" * 72)
    print("FinMind Single-Request Diagnostic Probe")
    print("=" * 72)
    print(f"Endpoint    : {BASE_URL}")
    print(f"Symbol      : {SYMBOL}")
    print(f"Working dir : {Path.cwd()}")
    print()

    if not TOKEN:
        print("ERROR: 找不到 FinMind token。")
        print("請確認 StockCatcher 根目錄 .env 有 FINMIND_TOKEN。")
        return 2

    results = []

    for name, start, end in TESTS:
        ok = run_one(name, start, end)
        results.append((name, ok))
        time.sleep(1.0)

    print()
    print("=" * 72)
    print("SUMMARY")
    print("=" * 72)

    for name, ok in results:
        print(f"{name:16s}: {'PASS' if ok else 'FAIL'}")

    passed = sum(ok for _, ok in results)
    print("-" * 72)
    print(f"Passed: {passed}/{len(results)}")

    if passed == len(results):
        print("結論：目前單筆 FinMind API 測試全部成功。")
    elif passed == 0:
        print("結論：目前所有單筆測試都失敗，請把完整輸出貼給我。")
    else:
        print("結論：不同日期範圍的結果不同，這很適合用來定位限制原因。")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
