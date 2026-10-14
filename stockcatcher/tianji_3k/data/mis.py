from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
import os
import threading
import time

try:
    from curl_cffi import requests as curl_requests
except ImportError:
    import requests as curl_requests

from .config import MIS_BATCH_SIZE, HTTP_TIMEOUT

TAIPEI = timezone(timedelta(hours=8))


class MISProvider:
    """Fetch market-wide MIS snapshots with bounded concurrent batches.

    Each worker owns a persistent HTTP session so cookies are not shared across
    threads. Batch failures are isolated: one failed batch does not discard
    successful batches or stop the Radar.
    """

    def __init__(self, stock_info_map=None, exchange_resolver=None):
        self.stock_info_map = stock_info_map or {}
        self.exchange_resolver = exchange_resolver or (lambda s: "tse")
        self.session = curl_requests.Session()
        self.initialized = False
        self._thread_local = threading.local()
        self._executor = None
        self._max_workers = max(1, int(os.getenv("TIANJI_MIS_FETCH_WORKERS", "4")))
        self.last_fetch_stats = {}

    def _ensure(self):
        if self.initialized:
            return
        try:
            self.session.get(
                "https://mis.twse.com.tw/stock/index.jsp",
                impersonate="chrome120",
                timeout=6,
            )
        except Exception:
            pass
        self.initialized = True

    def _worker_session(self):
        session = getattr(self._thread_local, "session", None)
        if session is None:
            session = curl_requests.Session()
            try:
                session.get(
                    "https://mis.twse.com.tw/stock/index.jsp",
                    impersonate="chrome120",
                    timeout=6,
                )
            except Exception:
                pass
            self._thread_local.session = session
        return session

    @staticmethod
    def _num(v):
        try:
            s = str(v).replace(",", "").strip()
            return 0.0 if s in {"", "-", "--", "null", "None"} else float(s)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _quote_timestamp(item, now=None):
        """Return the MIS last-trade timestamp, if its date/time is usable."""
        clock = str(item.get("t", "") or "").strip()
        date_text = str(item.get("d", "") or "").strip()
        if not clock or clock in {"-", "--", "null", "None"}:
            return None
        now = now or datetime.now(TAIPEI)
        try:
            if len(date_text) == 8 and date_text.isdigit():
                quote_dt = datetime.strptime(
                    f"{date_text} {clock}", "%Y%m%d %H:%M:%S"
                ).replace(tzinfo=TAIPEI)
            else:
                quote_dt = datetime.strptime(
                    f"{now:%Y%m%d} {clock}", "%Y%m%d %H:%M:%S"
                ).replace(tzinfo=TAIPEI)
            # Reject impossible/future timestamps rather than turning them into
            # a negative age that would appear fresher than the current quote.
            age = (now - quote_dt).total_seconds()
            if age < -5 or age > 24 * 60 * 60:
                return None
            return quote_dt
        except (TypeError, ValueError, OverflowError):
            return None

    def _fetch_chunk(self, batch, worker_session=False):
        session = self._worker_session() if worker_session else self.session
        ex = "|".join(
            f"{self.exchange_resolver(s)}_{s}.tw" for s in batch
        )
        out = {}
        failed = False
        stats = {
            "requested": len(batch), "raw_items": 0, "parsed": 0,
            "missing_symbol": 0, "invalid_previous_close": 0,
            "missing_last_price": 0, "quote_time_unknown": 0,
            "failed": False, "error_type": None,
        }
        try:
            response = session.get(
                "https://mis.twse.com.tw/stock/api/getStockInfo.jsp",
                params={"ex_ch": ex, "_": int(time.time() * 1000)},
                impersonate="chrome120",
                timeout=HTTP_TIMEOUT,
            )
            payload = response.json()
            received_at = datetime.now(TAIPEI)
            msg_array = payload.get("msgArray", [])
            stats["raw_items"] = len(msg_array) if isinstance(msg_array, list) else 0
            for item in msg_array if isinstance(msg_array, list) else []:
                sid = str(item.get("c", "")).strip()
                if not sid:
                    stats["missing_symbol"] += 1
                    continue
                y = self._num(item.get("y"))
                z = self._num(item.get("z"))
                # Keep parse-rejection reasons visible; never substitute the
                # previous close (`y`) for the last traded price (`z`).
                if y <= 0:
                    stats["invalid_previous_close"] += 1
                    continue
                if z <= 0:
                    stats["missing_last_price"] += 1
                    continue
                quote_dt = self._quote_timestamp(item, received_at)
                if quote_dt is None:
                    stats["quote_time_unknown"] += 1
                quote_age = (
                    max(0.0, (received_at - quote_dt).total_seconds())
                    if quote_dt is not None else None
                )
                # MIS `v` is cumulative volume in LOTS.
                v_lots = float(self._num(str(item.get("v", "0")).replace(",", "")))
                up = (z / y - 1) * 100 if y > 0 else 0.0
                identity = "|".join([
                    sid, str(item.get("t", "")), str(item.get("tv", "")),
                    str(item.get("z", "")), str(item.get("v", "")),
                    str(item.get("d", "")),
                ])
                out[sid] = {
                    "symbol": sid,
                    "current_price": z,
                    "previous_close": y,
                    "today_open": self._num(item.get("o", y)),
                    "cumulative_volume": v_lots,
                    "cumulative_volume_lots": v_lots,
                    "cumulative_volume_shares": v_lots * 1000.0,
                    "up_pct": round(up, 4),
                    "is_traded": str(item.get("z", "-")) not in {"-", "0"},
                    "data_identity": identity,
                    # observed_at is receive time for local volume-delta timing.
                    "observed_at": received_at,
                    # quote_time/age are the exchange's last-trade time and are
                    # used separately to prevent late alerts from stale prices.
                    "quote_time": quote_dt.isoformat() if quote_dt else None,
                    "quote_age_seconds": round(quote_age, 2) if quote_age is not None else None,
                    "quote_time_known": quote_dt is not None,
                }
                stats["parsed"] += 1
        except Exception as exc:
            failed = True
            stats["error_type"] = type(exc).__name__
        stats["failed"] = failed
        return out, failed, stats

    def fetch_batch(self):
        started = time.monotonic()
        symbols = list(self.stock_info_map)
        batch_size = max(1, int(MIS_BATCH_SIZE))
        batches = [symbols[i:i + batch_size] for i in range(0, len(symbols), batch_size)]
        out = {}
        failed_batches = 0
        batch_stats = []

        def merge_result(result, batch, batch_index):
            nonlocal failed_batches
            # Accept legacy two-tuples from tests/custom providers while the
            # production worker returns (quotes, failed, parse_stats).
            if isinstance(result, tuple) and len(result) >= 3:
                chunk_out, failed, stats = result[0], bool(result[1]), dict(result[2] or {})
            else:
                chunk_out, failed = result
                stats = {
                    "requested": len(batch), "raw_items": None,
                    "parsed": len(chunk_out), "missing_symbol": None,
                    "invalid_previous_close": None, "missing_last_price": None,
                    "quote_time_unknown": None, "error_type": None,
                }
            out.update(chunk_out)
            failed_batches += int(bool(failed))
            stats["failed"] = bool(failed)
            stats["batch"] = batch_index
            batch_stats.append(stats)

        if not batches:
            self.last_fetch_stats = {
                "elapsed_ms": (time.monotonic() - started) * 1000,
                "batches": 0, "workers": 0, "requested_symbols": 0,
                "returned_symbols": 0, "failed_batches": 0,
                "raw_items": 0, "missing_symbol": 0,
                "invalid_previous_close": 0, "missing_last_price": 0,
                "quote_time_unknown": 0, "batch_stats": [],
            }
            return out

        if len(batches) == 1:
            self._ensure()
            result = self._fetch_chunk(batches[0], worker_session=False)
            merge_result(result, batches[0], 1)
            workers_used = 1
        else:
            if self._executor is None:
                self._executor = ThreadPoolExecutor(
                    max_workers=self._max_workers,
                    thread_name_prefix="tianji-mis",
                )
            futures = {
                self._executor.submit(self._fetch_chunk, batch, True): (i, batch)
                for i, batch in enumerate(batches, start=1)
            }
            for future in as_completed(futures):
                batch_index, batch = futures[future]
                try:
                    merge_result(future.result(), batch, batch_index)
                except Exception as exc:
                    failed_batches += 1
                    batch_stats.append({
                        "batch": batch_index, "requested": len(batch),
                        "raw_items": None, "parsed": 0, "failed": True,
                        "error_type": type(exc).__name__,
                    })
            workers_used = min(self._max_workers, len(batches))

        known = lambda key: sum(int(x.get(key) or 0) for x in batch_stats if x.get(key) is not None)
        self.last_fetch_stats = {
            "elapsed_ms": round((time.monotonic() - started) * 1000, 1),
            "batches": len(batches),
            "workers": workers_used,
            "requested_symbols": len(symbols),
            "returned_symbols": len(out),
            "failed_batches": failed_batches,
            "raw_items": known("raw_items") if all(x.get("raw_items") is not None for x in batch_stats) else None,
            "missing_symbol": known("missing_symbol") if all(x.get("missing_symbol") is not None for x in batch_stats) else None,
            "invalid_previous_close": known("invalid_previous_close") if all(x.get("invalid_previous_close") is not None for x in batch_stats) else None,
            "missing_last_price": known("missing_last_price") if all(x.get("missing_last_price") is not None for x in batch_stats) else None,
            "quote_time_unknown": known("quote_time_unknown") if all(x.get("quote_time_unknown") is not None for x in batch_stats) else None,
            "batch_stats": sorted(batch_stats, key=lambda x: x.get("batch", 0)),
        }
        return out
