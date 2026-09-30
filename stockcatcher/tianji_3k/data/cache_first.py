from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional, Tuple

import pandas as pd

from .data_integrity import validate_ohlc_frame
from .market_data import FinMindDailyProvider, standardize_daily_frame
from .trading_calendar import TaiwanTradingCalendar
from .finmind_budget import FinMindRequestBudget, FinMindCircuitOpen

log = logging.getLogger("tianji_3k.cache")


class CacheFirstDailyProvider:
    """Calendar-aware incremental daily provider.

    Production policy
    -----------------
    1. Trading Calendar decides which dates are market trading dates.
    2. Local cache is always inspected first.
    3. FinMind is only used for missing historical data.
    4. A stock does NOT need to have a bar on every market trading day.
       Individual suspension / non-trading periods are legal.
    5. Stage 1 / Production initialization validates the actual number of
       valid OHLCV bars instead of requiring every global trading date.
    6. Fetched/cache data is validated before persistence.
    7. Writes are atomic.
    8. FinMind quota errors immediately open the circuit breaker.
    """

    def __init__(
        self,
        token: str,
        cache_dir: Optional[str | Path] = None,
        calendar: TaiwanTradingCalendar | None = None,
        budget: FinMindRequestBudget | None = None,
    ):
        self.fallback = FinMindDailyProvider(token)

        self.budget = budget or FinMindRequestBudget(limit=580)

        self.cache_dir = Path(
            cache_dir
            or (
                Path(__file__).resolve().parents[1]
                / "cache"
                / "daily"
            )
        )
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        self.calendar = calendar

        # Runtime statistics
        self.cache_hits = 0
        self.cache_partial = 0
        self.cache_misses = 0
        self.cache_invalid = 0

        self.finmind_fallbacks = 0
        self.finmind_failures = 0
        self.finmind_rows_fetched = 0

        self.cache_updates = 0

        self.last_source = None
        self.last_ranges: list[str] = []

        # Compatibility alias used by the rest of Tianji 3K.
        self.finmind_budget = self.budget

    # ------------------------------------------------------------------
    # Date helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _to_date(value) -> pd.Timestamp:
        return pd.Timestamp(value).normalize()

    @staticmethod
    def _date_str(value: pd.Timestamp) -> str:
        return value.strftime("%Y-%m-%d")

    # ------------------------------------------------------------------
    # Trading calendar
    # ------------------------------------------------------------------

    def _expected_trading_days(
        self,
        start: pd.Timestamp,
        end: pd.Timestamp,
    ) -> set:
        """Return expected market trading dates.

        IMPORTANT
        ---------
        This method must never implicitly access the network.

        Production:
            An explicit TaiwanTradingCalendar is supplied.

        Tests / offline:
            Use weekday fallback only.

        This separation prevents CacheFirstDailyProvider from unexpectedly
        consuming FinMind requests during unit tests or offline operations.
        """

        if self.calendar is not None:
            return set(
                self.calendar.expected_trading_days(
                    start.date(),
                    end.date(),
                )
            )

        return set(
            pd.bdate_range(start, end).date
        )

    # ------------------------------------------------------------------
    # Cache discovery
    # ------------------------------------------------------------------

    def _candidate_files(self, symbol: str):
        prefix = f"TaiwanStockPrice_{str(symbol).strip()}_"

        return sorted(
            (
                p
                for p in self.cache_dir.glob(f"{prefix}*.json")
                if p.is_file()
            ),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )

    # ------------------------------------------------------------------
    # Cache reading / validation
    # ------------------------------------------------------------------

    def _read_file(self, path: Path) -> pd.DataFrame:
        raw = json.loads(
            path.read_text(encoding="utf-8")
        )

        if isinstance(raw, dict):
            raw = raw.get(
                "data",
                raw.get("result", []),
            )

        if not isinstance(raw, list):
            raise ValueError(
                "cache JSON root is not a list"
            )

        raw_df = pd.DataFrame(raw)

        if "date" not in raw_df.columns:
            raise ValueError(
                "cache missing date column"
            )

        raw_dates = (
            pd.to_datetime(
                raw_df["date"],
                errors="coerce",
            )
            .dt.normalize()
        )

        if raw_dates.isna().any():
            raise ValueError(
                "cache contains invalid date"
            )

        if raw_dates.duplicated(
            keep=False
        ).any():
            raise ValueError(
                "DUPLICATE_DATE_IN_FILE"
            )

        df = standardize_daily_frame(
            raw_df
        )

        integrity = validate_ohlc_frame(df)

        if not integrity.ok:
            raise ValueError(
                integrity.reason
            )

        return (
            df
            .sort_values("date")
            .reset_index(drop=True)
        )

    # ------------------------------------------------------------------
    # Frame merge
    # ------------------------------------------------------------------

    @staticmethod
    def _merge_frames(
        frames: list[pd.DataFrame],
    ) -> pd.DataFrame:
        if not frames:
            return pd.DataFrame()

        merged = pd.concat(
            frames,
            ignore_index=True,
        )

        merged["date"] = (
            pd.to_datetime(
                merged["date"],
                errors="coerce",
            )
            .dt.normalize()
        )

        merged = (
            merged
            .dropna(subset=["date"])
            .sort_values("date")
            .reset_index(drop=True)
        )

        # --------------------------------------------------------------
        # Duplicate-date conflict detection
        # --------------------------------------------------------------

        if merged["date"].duplicated(
            keep=False
        ).any():

            conflicts = []

            duplicated = merged[
                merged["date"].duplicated(
                    keep=False
                )
            ]

            for d, grp in duplicated.groupby(
                "date"
            ):
                cols = [
                    c
                    for c in (
                        "open",
                        "high",
                        "low",
                        "close",
                        "volume",
                    )
                    if c in grp.columns
                ]

                if len(
                    grp[cols].drop_duplicates()
                ) > 1:
                    conflicts.append(
                        d.strftime(
                            "%Y-%m-%d"
                        )
                    )

            if conflicts:
                raise ValueError(
                    "DATA_CONFLICT:"
                    + ",".join(conflicts)
                )

            # Same date / identical content:
            # keep latest copy.
            merged = merged.drop_duplicates(
                subset=["date"],
                keep="last",
            )

        integrity = validate_ohlc_frame(
            merged
        )

        if not integrity.ok:
            raise ValueError(
                integrity.reason
            )

        return (
            standardize_daily_frame(
                merged
            )
            .sort_values("date")
            .reset_index(drop=True)
        )

    # ------------------------------------------------------------------
    # Load cache union
    # ------------------------------------------------------------------

    def _load_cache_union(
        self,
        symbol: str,
        start: str,
        end: str,
    ) -> Tuple[
        Optional[pd.DataFrame],
        Optional[Path],
    ]:

        rs = self._to_date(start)
        re = self._to_date(end)

        frames = []
        newest = None

        for path in self._candidate_files(
            symbol
        ):
            try:
                df = self._read_file(path)

                inside = df[
                    (df.date >= rs)
                    & (df.date <= re)
                ]

                if not inside.empty:
                    frames.append(df)

                    if newest is None:
                        newest = path

            except Exception as exc:
                self.cache_invalid += 1

                log.warning(
                    "CACHE_INVALID %s: %s (%s)",
                    symbol,
                    type(exc).__name__,
                    path.name,
                )

        if not frames:
            return None, None

        return (
            self._merge_frames(frames),
            newest,
        )

    # ------------------------------------------------------------------
    # Missing trading days
    # ------------------------------------------------------------------

    def _missing_trading_days(
        self,
        cached_dates,
        start: pd.Timestamp,
        end: pd.Timestamp,
    ) -> pd.DatetimeIndex:

        expected = self._expected_trading_days(
            start,
            end,
        )

        cached = {
            pd.Timestamp(x).date()
            for x in pd.to_datetime(
                cached_dates,
                errors="coerce",
            ).dropna()
        }

        return pd.DatetimeIndex(
            [
                d
                for d in expected
                if d not in cached
            ]
        )

    # ------------------------------------------------------------------
    # Group missing dates
    # ------------------------------------------------------------------

    def _group_missing_by_calendar(
        self,
        missing: pd.DatetimeIndex,
        start: pd.Timestamp,
        end: pd.Timestamp,
    ):

        if len(missing) == 0:
            return []

        expected = self._expected_trading_days(
            start,
            end,
        )

        missing_set = {
            x.date()
            for x in missing
        }

        groups = []
        current = []

        for d in expected:

            if d in missing_set:
                current.append(d)

            elif current:
                groups.append(
                    (
                        current[0],
                        current[-1],
                    )
                )
                current = []

        if current:
            groups.append(
                (
                    current[0],
                    current[-1],
                )
            )

        return [
            (
                pd.Timestamp(a),
                pd.Timestamp(b),
            )
            for a, b in groups
        ]

    # ------------------------------------------------------------------
    # Cache persistence
    # ------------------------------------------------------------------

    def _write_merged_cache(
        self,
        symbol: str,
        df: pd.DataFrame,
    ) -> Path:

        x = self._merge_frames(
            [df]
        )

        if x.empty:
            raise ValueError(
                "cannot persist empty/invalid merged cache"
            )

        first = self._date_str(
            self._to_date(
                x.date.min()
            )
        )

        last = self._date_str(
            self._to_date(
                x.date.max()
            )
        )

        path = (
            self.cache_dir
            / (
                f"TaiwanStockPrice_"
                f"{symbol}_"
                f"{first}_"
                f"{last}.json"
            )
        )

        tmp = path.with_suffix(
            path.suffix + ".tmp"
        )

        tmp.write_text(
            x.to_json(
                orient="records",
                date_format="iso",
            ),
            encoding="utf-8",
        )

        tmp.replace(path)

        self.cache_updates += 1

        return path

    # ------------------------------------------------------------------
    # Error sanitization
    # ------------------------------------------------------------------

    @staticmethod
    def _sanitize_error(
        exc: Exception,
    ) -> str:

        msg = str(exc)

        for marker in (
            "access_token=",
            "token=",
            "Authorization: Bearer ",
        ):

            if marker in msg:

                before, _, after = (
                    msg.partition(marker)
                )

                if marker.endswith(" "):

                    msg = (
                        before
                        + marker
                        + "***REDACTED***"
                    )

                else:

                    tail = (
                        after.split(
                            "&",
                            1,
                        )[-1]
                        if "&" in after
                        else ""
                    )

                    msg = (
                        before
                        + marker
                        + "***REDACTED***"
                        + (
                            "&" + tail
                            if tail
                            else ""
                        )
                    )

        return msg[:1000]

    # ------------------------------------------------------------------
    # FinMind fetch
    # ------------------------------------------------------------------

    def _fetch(
        self,
        symbol: str,
        start: pd.Timestamp,
        end: pd.Timestamp,
    ) -> pd.DataFrame:

        if start > end:
            return pd.DataFrame()

        s = self._date_str(start)
        e = self._date_str(end)

        # --------------------------------------------------------------
        # Local rolling budget reservation
        # --------------------------------------------------------------

        self.budget.reserve(
            reason=(
                f"daily:{symbol}:"
                f"{s}~{e}"
            )
        )

        self.finmind_fallbacks += 1
        self.last_source = "finmind"
        self.last_ranges.append(
            f"{s}~{e}"
        )

        log.info(
            "FINMIND_FALLBACK %s %s~%s",
            symbol,
            s,
            e,
        )

        try:

            df = standardize_daily_frame(
                self.fallback.get_daily(
                    symbol,
                    s,
                    e,
                )
            )

            if df.empty:
                raise ValueError(
                    "FETCH_EMPTY"
                )

            # ----------------------------------------------------------
            # Provider may return a wider date range.
            #
            # Never merge rows outside the requested range.
            # ----------------------------------------------------------

            df["date"] = (
                pd.to_datetime(
                    df["date"],
                    errors="coerce",
                )
                .dt.normalize()
            )

            df = df[
                (df["date"] >= start)
                & (df["date"] <= end)
            ].copy()

            # ----------------------------------------------------------
            # Keep only actual Taiwan market trading dates.
            # ----------------------------------------------------------

            expected = set(
                self._expected_trading_days(
                    start,
                    end,
                )
            )

            df = df[
                df["date"]
                .dt.date
                .isin(expected)
            ].copy()

            if df.empty:
                raise ValueError(
                    "FETCH_EMPTY_AFTER_RANGE_FILTER"
                )

            integrity = validate_ohlc_frame(
                df
            )

            if not integrity.ok:
                raise ValueError(
                    integrity.reason
                )

            self.finmind_rows_fetched += len(
                df
            )

            self.budget.record_success()

            return df

        except Exception as exc:

            self.finmind_failures += 1

            msg = str(exc).lower()

            quota_hit = (
                "402" in msg
                or "quota" in msg
                or "upper limit" in msg
                or (
                    "requests reach "
                    "the upper limit"
                    in msg
                )
            )

            self.budget.record_failure(
                quota=quota_hit
            )

            log.error(
                "FINMIND_FAILED %s %s~%s: %s",
                symbol,
                s,
                e,
                self._sanitize_error(exc),
            )

            # ----------------------------------------------------------
            # Production rule:
            #
            # FinMind server quota reached
            #       ↓
            # FinMindCircuitOpen
            #       ↓
            # PAUSED_BUDGET
            #       ↓
            # checkpoint
            #       ↓
            # stop additional FinMind calls
            #
            # The Runner must NOT continue Stage 1–3 with incomplete
            # history.
            # ----------------------------------------------------------

            if quota_hit:

                raise FinMindCircuitOpen(
                    "FinMind server quota "
                    f"reached for {symbol} "
                    f"{s}~{e}"
                ) from exc

            raise

    # ------------------------------------------------------------------
    # Main daily data access
    # ------------------------------------------------------------------

    def get_daily(
        self,
        symbol: str,
        start: str,
        end: str,
        *,
        allow_symbol_non_trading: bool = False,
    ) -> pd.DataFrame:
        """Get daily OHLCV using cache-first incremental logic.

        IMPORTANT PRODUCTION FIX
        -------------------------
        `allow_symbol_non_trading=True` means:

            Global market trading date
            !=
            Individual stock must have a bar.

        Therefore a stock may legitimately have missing dates because of:

        - individual suspension
        - capital reduction
        - stock reissuance
        - temporary non-trading status
        - other legal individual-stock trading interruptions

        We therefore MUST NOT turn every missing global trading date into
        a one-day FinMind request.

        Example:

            3591
            2026-09-16

        FinMind may legitimately return no data for that individual stock
        on that date. A request like:

            2026-09-16 ~ 2026-09-16

        can therefore produce:

            FETCH_EMPTY

        That does NOT necessarily mean the historical dataset is invalid.

        In permissive production mode we instead fetch the requested
        historical window as a whole, then validate the actual number of
        valid stock bars at the initializer layer.

        This preserves the important rule:

            Stage 1 requires 61 VALID STOCK BARS,

        rather than:

            Stage 1 requires a bar on every global market trading day.
        """

        rs = self._to_date(start)
        re = self._to_date(end)

        if rs > re:
            raise ValueError(
                f"invalid date range: "
                f"{start} > {end}"
            )

        expected = self._expected_trading_days(
            rs,
            re,
        )

        self.last_ranges = []

        # ==============================================================
        # 1. CACHE-FIRST
        # ==============================================================

        cached, cache_path = (
            self._load_cache_union(
                symbol,
                start,
                end,
            )
        )

        # ==============================================================
        # 2. NO CACHE
        # ==============================================================

        if cached is None:

            self.cache_misses += 1

            df = self._fetch(
                symbol,
                rs,
                re,
            )

            have = {
                pd.Timestamp(x).date()
                for x in df["date"]
            }

            missing = [
                d.isoformat()
                for d in expected
                if d not in have
            ]

            # ----------------------------------------------------------
            # Strict mode:
            #
            # Every global trading day must exist.
            # ----------------------------------------------------------

            if (
                missing
                and not allow_symbol_non_trading
            ):

                raise RuntimeError(
                    "HISTORY_MISSING_AFTER_FETCH:"
                    + ",".join(missing)
                )

            # ----------------------------------------------------------
            # Production permissive mode:
            #
            # Missing global dates may be legitimate individual-stock
            # non-trading dates.
            # ----------------------------------------------------------

            if (
                missing
                and allow_symbol_non_trading
            ):

                log.info(
                    "SYMBOL_NON_TRADING_DATES "
                    "%s missing=%d",
                    symbol,
                    len(missing),
                )

            self._write_merged_cache(
                symbol,
                df,
            )

            return standardize_daily_frame(
                df
            )

        # ==============================================================
        # 3. CACHE COMPLETE
        # ==============================================================

        missing = self._missing_trading_days(
            cached["date"],
            rs,
            re,
        )

        if len(missing) == 0:

            self.cache_hits += 1
            self.last_source = "cache"

            return standardize_daily_frame(
                cached[
                    (cached.date >= rs)
                    & (cached.date <= re)
                ].copy()
            )

        # ==============================================================
        # 4. CACHE PARTIAL
        # ==============================================================

        self.cache_partial += 1

        pieces = [cached]

        overlapping_files = [
            p
            for p in self._candidate_files(
                symbol
            )
            if p.exists()
        ]

        # ==============================================================
        # IMPORTANT FIX FOR 3591 / FETCH_EMPTY
        # ==============================================================
        #
        # Previous behavior:
        #
        #   cache partial
        #        ↓
        #   detect missing global trading date
        #        ↓
        #   group missing dates
        #        ↓
        #   FinMind request for one date
        #
        # Example:
        #
        #   3591
        #   2026-09-16
        #
        # Result:
        #
        #   FinMind 2026-09-16 ~ 2026-09-16
        #   FETCH_EMPTY
        #
        # This was incorrect for a legitimately suspended/non-trading
        # individual stock.
        #
        # Production permissive mode therefore uses the FULL requested
        # history window when a cache is partial.
        #
        # This lets FinMind return the stock's actual available bars and
        # lets the initializer decide whether the stock has enough VALID
        # bars (61) for Stage 1.
        #
        # ==============================================================
        if allow_symbol_non_trading:

            log.info(
                "CACHE_PARTIAL_SYMBOL_NON_TRADING "
                "%s missing=%d -> "
                "FULL_WINDOW_BACKFILL %s~%s",
                symbol,
                len(missing),
                self._date_str(rs),
                self._date_str(re),
            )

            pieces.append(
                self._fetch(
                    symbol,
                    rs,
                    re,
                )
            )

        # ==============================================================
        # STRICT MODE
        # ==============================================================
        #
        # Keep the original fragment-aware behavior.
        #
        # This mode is useful for tests / strict data-integrity callers.
        #
        else:

            interior_missing = any(
                (
                    pd.Timestamp(d)
                    > cached["date"].min()
                    and
                    pd.Timestamp(d)
                    < cached["date"].max()
                )
                for d in missing
            )

            # ----------------------------------------------------------
            # Single canonical cache file with an internal gap:
            #
            # Preserve V1.2.2 orchestration contract:
            # one history request per symbol.
            # ----------------------------------------------------------

            if (
                interior_missing
                and len(overlapping_files) == 1
            ):

                pieces.append(
                    self._fetch(
                        symbol,
                        rs,
                        re,
                    )
                )

            # ----------------------------------------------------------
            # Fragmented cache:
            #
            # Only request actual missing calendar ranges.
            # ----------------------------------------------------------

            else:

                for (
                    gs,
                    ge,
                ) in self._group_missing_by_calendar(
                    missing,
                    rs,
                    re,
                ):

                    pieces.append(
                        self._fetch(
                            symbol,
                            gs,
                            ge,
                        )
                    )

        # ==============================================================
        # 5. MERGE CACHE + FINMIND
        # ==============================================================

        merged = self._merge_frames(
            [
                p
                for p in pieces
                if p is not None
                and not p.empty
            ]
        )

        have = {
            pd.Timestamp(x).date()
            for x in merged["date"]
        }

        still_missing = [
            d.isoformat()
            for d in expected
            if d not in have
        ]

        # ==============================================================
        # 6. STRICT VALIDATION
        # ==============================================================

        if (
            still_missing
            and not allow_symbol_non_trading
        ):

            raise RuntimeError(
                "HISTORY_MISSING_AFTER_BACKFILL:"
                + ",".join(still_missing)
            )

        # ==============================================================
        # 7. PRODUCTION INDIVIDUAL-STOCK NON-TRADING
        # ==============================================================

        if (
            still_missing
            and allow_symbol_non_trading
        ):

            log.info(
                "SYMBOL_NON_TRADING_DATES "
                "%s missing=%d",
                symbol,
                len(still_missing),
            )

        # ==============================================================
        # 8. PERSIST MERGED CACHE
        # ==============================================================

        self._write_merged_cache(
            symbol,
            merged,
        )

        log.info(
            "CACHE_UPDATE %s rows=%d "
            "range=%s~%s source=%s",
            symbol,
            len(merged),
            self._date_str(
                self._to_date(
                    merged.date.min()
                )
            ),
            self._date_str(
                self._to_date(
                    merged.date.max()
                )
            ),
            (
                cache_path.name
                if cache_path
                else "none"
            ),
        )

        self.last_source = (
            "cache+finmind"
        )

        return standardize_daily_frame(
            merged[
                (merged.date >= rs)
                & (merged.date <= re)
            ].copy()
        )

    # ------------------------------------------------------------------
    # Runtime statistics
    # ------------------------------------------------------------------

    def stats(self) -> dict:
        return {
            "cache_hits": self.cache_hits,
            "cache_partial": self.cache_partial,
            "cache_misses": self.cache_misses,
            "cache_invalid": self.cache_invalid,
            "finmind_fallbacks": self.finmind_fallbacks,
            "finmind_failures": self.finmind_failures,
            "finmind_rows_fetched": self.finmind_rows_fetched,
            "cache_updates": self.cache_updates,
            "last_source": self.last_source,
            "last_ranges": list(
                self.last_ranges
            ),
            "finmind_budget": (
                self.budget.snapshot()
            ),
            "cache_dir": str(
                self.cache_dir
            ),
        }
