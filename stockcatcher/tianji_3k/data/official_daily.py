from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Any

import pandas as pd
import requests

from .market_data import standardize_daily_frame

LOG = logging.getLogger("tianji_3k.official_daily")
TAIPEI = timezone(timedelta(hours=8))

TWSE_URL = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
TPEX_URL = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_quotes"


@dataclass
class OfficialDailyResult:
    trade_date: str
    twse_rows: int
    tpex_rows: int
    total_rows: int
    status: str
    errors: list[str]


class OfficialDailySnapshotProvider:
    """Fetch one full-market daily snapshot from TWSE + TPEx.

    This provider is intentionally market-level, not symbol-level: one TWSE
    request and one TPEx request populate the local daily cache. FinMind is
    reserved for historical gaps that remain after this snapshot is merged.
    """

    def __init__(self, timeout: int = 15, session: requests.Session | None = None):
        self.timeout = int(timeout)
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": "Mozilla/5.0 Tianji-3K/1.0"})

    @staticmethod
    def _num(v: Any):
        if v is None or str(v).strip() in {"", "-", "--", "null", "None"}:
            return None
        try:
            return float(str(v).replace(",", "").strip())
        except (TypeError, ValueError):
            return None

    @classmethod
    def _pick(cls, row: dict, *names):
        for name in names:
            if name in row and row[name] not in (None, "", "-"):
                return row[name]
        return None

    def _get(self, url: str):
        r = self.session.get(url, timeout=self.timeout)
        r.raise_for_status()
        payload = r.json()
        if not isinstance(payload, list):
            raise RuntimeError(f"OFFICIAL_DAILY_BAD_PAYLOAD:{url}")
        return payload

    def _parse_twse(self, rows: list[dict], trade_date: str) -> pd.DataFrame:
        out = []
        for r in rows:
            sid = str(self._pick(r, "Code", "StockCode", "股票代號") or "").strip()
            if len(sid) != 4 or not sid.isdigit():
                continue
            o = self._num(self._pick(r, "OpeningPrice", "Open", "開盤價"))
            h = self._num(self._pick(r, "HighestPrice", "High", "最高價"))
            l = self._num(self._pick(r, "LowestPrice", "Low", "最低價"))
            c = self._num(self._pick(r, "ClosingPrice", "Close", "收盤價"))
            v = self._num(self._pick(r, "TradeVolume", "TradingShares", "成交股數"))
            if None in (o, h, l, c, v):
                continue
            out.append({"date": trade_date, "stock_id": sid, "open": o, "high": h,
                        "low": l, "close": c, "volume": v, "source": "TWSE_OFFICIAL"})
        return standardize_daily_frame(pd.DataFrame(out))

    def _parse_tpex(self, rows: list[dict], trade_date: str) -> pd.DataFrame:
        out = []
        for r in rows:
            sid = str(self._pick(r, "SecuritiesCompanyCode", "Code", "SecuritiesCode", "股票代號") or "").strip()
            if len(sid) != 4 or not sid.isdigit():
                continue
            o = self._num(self._pick(r, "OpeningPrice", "Open", "開盤價"))
            h = self._num(self._pick(r, "HighestPrice", "High", "最高價"))
            l = self._num(self._pick(r, "LowestPrice", "Low", "最低價"))
            c = self._num(self._pick(r, "ClosingPrice", "Close", "收盤價"))
            v = self._num(self._pick(r, "TradingShares", "TradeVolume", "成交股數"))
            if None in (o, h, l, c, v):
                continue
            out.append({"date": trade_date, "stock_id": sid, "open": o, "high": h,
                        "low": l, "close": c, "volume": v, "source": "TPEX_OFFICIAL"})
        return standardize_daily_frame(pd.DataFrame(out))

    def fetch(self, trade_date: str) -> tuple[pd.DataFrame, pd.DataFrame]:
        twse_raw = self._get(TWSE_URL)
        tpex_raw = self._get(TPEX_URL)
        twse = self._parse_twse(twse_raw, trade_date)
        tpex = self._parse_tpex(tpex_raw, trade_date)
        if twse.empty and tpex.empty:
            raise RuntimeError(f"OFFICIAL_DAILY_EMPTY:{trade_date}")
        return twse, tpex

    def fetch_result(self, trade_date: str) -> tuple[OfficialDailyResult, pd.DataFrame]:
        errors: list[str] = []
        try:
            twse, tpex = self.fetch(trade_date)
        except Exception as exc:
            LOG.exception("OFFICIAL_DAILY_FETCH_FAILED trade_date=%s", trade_date)
            return OfficialDailyResult(trade_date, 0, 0, 0, "FAILED", [f"{type(exc).__name__}: {exc}"[:500]]), pd.DataFrame()
        merged = pd.concat([twse, tpex], ignore_index=True)
        merged = merged.drop_duplicates(subset=["stock_id", "date"], keep="last")
        return OfficialDailyResult(trade_date, len(twse), len(tpex), len(merged), "READY", errors), merged
