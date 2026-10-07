from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import requests
from requests import HTTPError


TAIPEI = timezone(timedelta(hours=8))


class FugleAPIError(RuntimeError):
    """Structured Fugle HTTP/auth failure for safe Radar degradation."""

    def __init__(self, symbol: str, status_code: int | None, message: str):
        self.symbol = str(symbol)
        self.status_code = status_code
        self.message = message
        super().__init__(message)


class FugleProvider:
    """Minimal Production Fugle adapter for intraday 5-minute confirmation."""

    URL = "https://api.fugle.tw/marketdata/v1.0/stock/intraday/candles/{symbol}"

    def __init__(self, api_key: str, timeout: int = 8):
        self.api_key = (api_key or "").strip()
        self.timeout = int(timeout)

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def get_5m_bars(self, symbol: str, limit: int | None = None) -> list[dict[str, Any]]:
        if not self.enabled:
            return []
        try:
            response = requests.get(
                self.URL.format(symbol=str(symbol)),
                headers={"X-API-KEY": self.api_key},
                params={"timeframe": "5"},
                timeout=self.timeout,
            )
            response.raise_for_status()
        except HTTPError as exc:
            status = getattr(exc.response, "status_code", None)
            raise FugleAPIError(str(symbol), status, f"HTTP {status or 'ERROR'}: {exc}") from exc
        except requests.RequestException as exc:
            raise FugleAPIError(str(symbol), None, f"REQUEST_ERROR: {exc}") from exc
        try:
            payload = response.json()
        except ValueError as exc:
            raise FugleAPIError(str(symbol), response.status_code, "INVALID_JSON_RESPONSE") from exc
        raw = payload.get("data", payload.get("candles", []))
        if not isinstance(raw, list):
            return []

        now = datetime.now(TAIPEI)
        out: list[dict[str, Any]] = []
        for item in raw:
            try:
                date = item.get("date")
                if not date:
                    continue
                dt = datetime.fromisoformat(str(date).replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=TAIPEI)
                dt = dt.astimezone(TAIPEI)
                # Never use the currently forming 5-minute candle.
                if dt + timedelta(minutes=5) > now:
                    continue
                out.append({
                    "date": dt.isoformat(),
                    "open": float(item["open"]),
                    "high": float(item["high"]),
                    "low": float(item["low"]),
                    "close": float(item["close"]),
                    "volume": float(item["volume"]),
                })
            except (KeyError, TypeError, ValueError):
                continue
        out.sort(key=lambda x: x["date"])
        return out


    def check_5m_access(self, symbol: str) -> dict[str, Any]:
        """One-shot connectivity/auth check; does not require 23 bars."""
        if not self.enabled:
            return {"ok": False, "status": "DISABLED", "symbol": str(symbol), "bars": 0}
        bars = self.get_5m_bars(symbol)
        return {"ok": True, "status": "OK", "symbol": str(symbol), "bars": len(bars)}

    def evaluate_3k_micro_breakout(self, symbol: str, min_volume_ratio: float = 1.05) -> dict[str, Any] | None:
        """Use the scanner.py-style completed-5m-bar structure.

        The 5m layer is a confirmation layer. The existing Production
        projected-volume >=1.5 gate remains the final volume gate.
        """
        bars = self.get_5m_bars(symbol)
        if len(bars) < 23:
            return None
        first, second, third = bars[-3:]
        baseline = bars[:-3][-20:]
        avg_volume = sum(float(x["volume"]) for x in baseline) / len(baseline)
        if avg_volume <= 0:
            return None
        breakout_price = max(float(first["high"]), float(second["high"]))
        third_close = float(third["close"])
        third_volume = float(third["volume"])
        volume_ratio = third_volume / avg_volume
        # Keep the scanner's basic 5m volume multiplier (1.2x) as the
        # micro-confirmation threshold; the Production 1.5x projected daily
        # volume gate remains unchanged and is checked separately.
        if third_close <= breakout_price or volume_ratio < float(min_volume_ratio):
            return None
        return {
            "bar_time": third["date"],
            "breakout_price": breakout_price,
            "close": third_close,
            "volume": third_volume,
            "volume_ratio": volume_ratio,
            "required_volume": avg_volume * float(min_volume_ratio),
            "required_volume_ratio": float(min_volume_ratio),
            "ma20": sum(float(x["close"]) for x in baseline) / len(baseline),
            "stop_price": min(float(first["low"]), float(second["low"]), float(third["low"])),
            "bars_used": 23,
        }
