"""Stage 0 minimal volume bootstrap from official exchange whole-market snapshots."""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import requests

LOG = logging.getLogger("tianji_3k.stage0_volume_bootstrap")

TWSE_URL = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
TPEX_URL = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"


def _s(v: Any) -> str:
    return str(v).strip() if v is not None else ""


def _num(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _iso_date(v: Any) -> str | None:
    s = _s(v).replace("/", "-")
    if not s:
        return None
    if len(s) == 7 and s.isdigit():  # ROC YYYMMDD
        return f"{int(s[:3]) + 1911:04d}-{s[3:5]}-{s[5:7]}"
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            pass
    return None


def _rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        for key in ("data", "Data", "rows", "result", "results"):
            if isinstance(payload.get(key), list):
                return [x for x in payload[key] if isinstance(x, dict)]
    return []


def _pick(row: dict[str, Any], keys: Iterable[str]) -> Any:
    for k in keys:
        if k in row and row[k] not in (None, ""):
            return row[k]
    return None


def _normalize(rows: list[dict[str, Any]], market: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        symbol = _s(_pick(row, (
            "Code", "code", "SecuritiesCompanyCode", "SecuritiesCode", "stock_id", "symbol", "Symbol"
        )))
        if not symbol.isdigit() or len(symbol) not in (4, 5, 6):
            continue
        date = _iso_date(_pick(row, ("Date", "date", "trade_date", "TradeDate")))
        volume = _num(_pick(row, (
            "TradeVolume", "TradingShares", "Trading_Volume", "volume_shares", "volume", "成交股數"
        )))
        if not date or volume is None or volume < 0:
            continue
        out.append({
            "stock_id": symbol,
            "date": date,
            "volume_shares": volume,
            "volume_lots": volume / 1000.0,
            "source": f"official:{market}_daily_snapshot",
        })
    return out


def _existing_snapshot(path: Path, latest_completed: str) -> int:
    if not path.exists():
        return 0
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = payload.get("rows", payload) if isinstance(payload, dict) else payload
        if not isinstance(rows, list):
            return 0
        return sum(1 for x in rows if isinstance(x, dict) and _s(x.get("date")) == latest_completed)
    except Exception:
        return 0


def bootstrap(
    cache_dir: str | Path,
    latest_completed: str,
    *,
    timeout: float = 20.0,
    session: Any = requests,
) -> dict[str, Any]:
    """Populate one whole-market volume cache snapshot for Stage 0.

    This is deliberately NOT FinMind. It uses one official whole-market
    snapshot per exchange, then Stage 0 consumes it through the existing
    cache-first loader. If the snapshot cannot be obtained for a market,
    existing cache remains usable and the caller can decide whether to fail
    closed or continue with UNKNOWN rows.
    """
    cache = Path(cache_dir)
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / f"stage0_volume_{latest_completed}.json"
    existing = _existing_snapshot(path, latest_completed)
    if existing:
        return {
            "status": "CACHE_HIT",
            "path": str(path),
            "latest_completed": latest_completed,
            "rows": existing,
            "markets_ok": {"TWSE": True, "TPEx": True},
            "requests": 0,
        }

    market_results: dict[str, Any] = {}
    normalized: list[dict[str, Any]] = []
    for market, url in (("TWSE", TWSE_URL), ("TPEx", TPEX_URL)):
        try:
            response = session.get(url, timeout=timeout, headers={"User-Agent": "tianji-3k/1.2"})
            response.raise_for_status()
            parsed = _normalize(_rows(response.json()), market)
            matching = [x for x in parsed if x["date"] == latest_completed]
            market_results[market] = {"ok": True, "rows": len(matching), "endpoint_rows": len(parsed)}
            normalized.extend(matching)
        except Exception as exc:
            market_results[market] = {"ok": False, "rows": 0, "error": f"{type(exc).__name__}: {exc}"}
            LOG.warning("STAGE0_VOLUME_BOOTSTRAP_FAILED market=%s error=%s", market, exc)

    # Require each exchange snapshot to match the calendar's latest completed K.
    # This prevents silently using a stale/latest-available date as yesterday's volume.
    failed = [m for m, x in market_results.items() if not x.get("ok") or x.get("rows", 0) == 0]
    if failed:
        return {
            "status": "FAILED",
            "path": str(path),
            "latest_completed": latest_completed,
            "rows": len(normalized),
            "markets_ok": {m: bool(x.get("ok") and x.get("rows", 0) > 0) for m, x in market_results.items()},
            "market_results": market_results,
            "requests": 2,
            "message": "Official Stage 0 volume snapshot missing/failed: " + ",".join(failed),
        }

    # One canonical daily-cache JSON is enough for the existing loader.
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    return {
        "status": "REFRESHED",
        "path": str(path),
        "latest_completed": latest_completed,
        "rows": len(normalized),
        "markets_ok": {m: True for m in market_results},
        "market_results": market_results,
        "requests": 2,
    }
