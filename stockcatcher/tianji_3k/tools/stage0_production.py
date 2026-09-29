"""天機 3K — Stage 0 Production Resolver / Audit V3.

Uses the existing Universe + daily cache and official TWSE/TPEx OpenAPI reference
sets for product classification and current trading status.  Unknown is never
silently converted to PASS.
"""
from __future__ import annotations

import argparse
import json
import logging
import re
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

import requests

from .stage0_audit import (
    SYMBOL_RE, CacheVolume, AuditRow, dedupe_universe, find_cache_dir,
    find_repo_root, load_cache_volumes, load_universe, _norm, _num,
    _date_key, classify_product, classify_status,
)

LOG = logging.getLogger("stage0_production")
TWSE = "https://openapi.twse.com.tw/v1"
TPEX = "https://www.tpex.org.tw/openapi/v1"

# Official endpoints.  They are public OpenAPI endpoints and require no token.
REF_ENDPOINTS = {
    "twse_main": f"{TWSE}/exchangeReport/STOCK_DAY_ALL",
    "twse_fund": f"{TWSE}/opendata/t187ap47_L",
    "twse_warrant": f"{TWSE}/opendata/t187ap37_L",
    "twse_suspend": f"{TWSE}/exchangeReport/TWTAWU",
    "twse_disposal": f"{TWSE}/announcement/punish",
    "tpex_main": f"{TPEX}/tpex_mainboard_quotes",
    "tpex_warrant": f"{TPEX}/tpex_warrant_issue",
    "tpex_fund": f"{TPEX}/tpex_opfund_latest",
    "tpex_suspend": f"{TPEX}/tpex_spendi_today",
    "tpex_disposal": f"{TPEX}/tpex_disposal_information",
    "tpex_cmode": f"{TPEX}/tpex_cmode",
}

SYMBOL_KEYS = (
    "Code", "code", "SecuritiesCompanyCode", "SecuritiesCode", "SecurityCode",
    "股票代號", "證券代號", "證券代碼", "stock_id", "symbol", "Symbol",
)


def _extract_symbol(row: Dict[str, Any]) -> str:
    for key in SYMBOL_KEYS:
        value = _norm(row.get(key))
        if SYMBOL_RE.fullmatch(value):
            return value
    # Some feeds put code in a longer string such as "0050 元大台灣50".
    for value in row.values():
        text = _norm(value)
        m = re.search(r"(?<!\d)(\d{4})(?!\d)", text)
        if m:
            return m.group(1)
    return ""


def _payload_rows(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        for key in ("data", "Data", "rows", "result", "results"):
            value = payload.get(key)
            if isinstance(value, list):
                return [x for x in value if isinstance(x, dict)]
    return []


def _truthy_status(row: Dict[str, Any], needles: Iterable[str]) -> bool:
    text = " ".join(f"{k}:{v}" for k, v in row.items()).lower()
    return any(n.lower() in text for n in needles)


@dataclass
class ReferenceSnapshot:
    fetched_at: str
    sets: Dict[str, List[str]]
    endpoint_ok: Dict[str, bool]
    endpoint_rows: Dict[str, int]
    endpoint_errors: Dict[str, str]

    def to_json(self) -> Dict[str, Any]:
        return asdict(self)


class OfficialReferenceResolver:
    """Builds a conservative official-reference snapshot.

    A symbol is classified as COMMON_STOCK only when its market mainboard feed
    is available and the symbol is not present in an official excluded-product
    feed.  Status is NORMAL only when the relevant market status feeds were
    successfully fetched and the symbol is absent from current suspension,
    disposal, and abnormal-trading feeds.
    """

    def __init__(self, cache_file: Path, timeout: float = 12.0, ttl_hours: float = 6.0,
                 refresh: bool = False):
        self.cache_file = cache_file
        self.timeout = timeout
        self.ttl_hours = ttl_hours
        self.refresh = refresh
        self.snapshot: Optional[ReferenceSnapshot] = None

    def _load_cached(self) -> Optional[ReferenceSnapshot]:
        if self.refresh or not self.cache_file.exists():
            return None
        try:
            payload = json.loads(self.cache_file.read_text(encoding="utf-8"))
            fetched = datetime.fromisoformat(payload["fetched_at"])
            age = (datetime.now(timezone.utc) - fetched).total_seconds() / 3600
            if age > self.ttl_hours:
                return None
            return ReferenceSnapshot(
                payload["fetched_at"], payload.get("sets", {}),
                payload.get("endpoint_ok", {}), payload.get("endpoint_rows", {}),
                payload.get("endpoint_errors", {}),
            )
        except Exception:
            return None

    def _get(self, name: str, url: str) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        try:
            r = requests.get(url, timeout=self.timeout, headers={"User-Agent": "tianji-3k/1.0"})
            r.raise_for_status()
            rows = _payload_rows(r.json())
            return rows, None
        except Exception as exc:
            return [], f"{type(exc).__name__}: {exc}"

    def build(self) -> ReferenceSnapshot:
        cached = self._load_cached()
        if cached:
            self.snapshot = cached
            return cached

        sets: Dict[str, List[str]] = {}
        endpoint_ok: Dict[str, bool] = {}
        endpoint_rows: Dict[str, int] = {}
        endpoint_errors: Dict[str, str] = {}

        for name, url in REF_ENDPOINTS.items():
            rows, error = self._get(name, url)
            endpoint_ok[name] = error is None
            endpoint_rows[name] = len(rows)
            if error:
                endpoint_errors[name] = error
            symbols: Set[str] = set()
            for row in rows:
                sid = _extract_symbol(row)
                if sid:
                    symbols.add(sid)
            sets[name] = sorted(symbols)

        snap = ReferenceSnapshot(
            datetime.now(timezone.utc).isoformat(), sets, endpoint_ok,
            endpoint_rows, endpoint_errors,
        )
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)
        self.cache_file.write_text(json.dumps(snap.to_json(), ensure_ascii=False, indent=2), encoding="utf-8")
        self.snapshot = snap
        return snap

    def _set(self, name: str) -> Set[str]:
        assert self.snapshot is not None
        return set(self.snapshot.sets.get(name, []))

    def product(self, row: Dict[str, Any]) -> Tuple[str, str]:
        sid = _norm(row.get("symbol") or row.get("stock_id") or row.get("Code"))
        market = _norm(row.get("market"))
        if market == "TWSE":
            excluded = (
                ("twse_warrant", "WARRANT"),
                ("twse_fund", "ETF"),
            )
            for source, label in excluded:
                if sid in self._set(source):
                    return label, f"official:{source}"
            main = self._set("twse_main")
            if self.snapshot and self.snapshot.endpoint_ok.get("twse_main") and sid in main:
                return "COMMON_STOCK", "official:twse_main"
        elif market in {"TPEx", "TPEX", "OTC"}:
            if sid in self._set("tpex_warrant"):
                return "WARRANT", "official:tpex_warrant"
            if sid in self._set("tpex_fund"):
                return "ETF", "official:tpex_fund"
            main = self._set("tpex_main")
            if self.snapshot and self.snapshot.endpoint_ok.get("tpex_main") and sid in main:
                return "COMMON_STOCK", "official:tpex_main"
        # Fall back to explicitly supplied fields, but keep hardcoded Universe
        # security_type=common_stock untrusted by default.
        return classify_product(row, trust_universe_fields=False)

    def status(self, row: Dict[str, Any]) -> Tuple[str, str]:
        sid = _norm(row.get("symbol") or row.get("stock_id") or row.get("Code"))
        market = _norm(row.get("market"))
        if market == "TWSE":
            relevant = ("twse_suspend", "twse_disposal")
        elif market in {"TPEx", "TPEX", "OTC"}:
            relevant = ("tpex_suspend", "tpex_disposal", "tpex_cmode")
        else:
            relevant = ()
        if relevant and all(self.snapshot and self.snapshot.endpoint_ok.get(x, False) for x in relevant):
            if sid in self._set("twse_disposal") or sid in self._set("tpex_disposal"):
                return "DISPOSAL", "official:disposal"
            if sid in self._set("twse_suspend") or sid in self._set("tpex_suspend"):
                return "SUSPENDED", "official:suspend"
            if sid in self._set("tpex_cmode"):
                return "ABNORMAL", "official:tpex_cmode"
            return "NORMAL", "official:status_feeds"
        # Explicit row fields are acceptable only when present; absence remains unknown.
        return classify_status(row)


def evaluate_stage0(row: Dict[str, Any], volume: Optional[CacheVolume], resolver: OfficialReferenceResolver,
                    threshold: float) -> AuditRow:
    sid = _norm(row.get("symbol") or row.get("stock_id") or row.get("Code"))
    result = AuditRow(symbol=sid, name=_norm(row.get("name") or row.get("Name")), market=_norm(row.get("market")))
    product, product_source = resolver.product(row)
    status, status_source = resolver.status(row)
    result.product_type, result.product_source = product, product_source
    result.status, result.status_source = status, status_source

    # Fixed order. UNKNOWN becomes first_exclusion, not PASS.
    if product == "UNKNOWN":
        result.first_exclusion = "PRODUCT_TYPE_UNKNOWN"
        result.first_exclusion_detail = "商品類型未能由官方參照集或明確欄位驗證"
        return result
    if product != "COMMON_STOCK":
        result.first_exclusion = f"PRODUCT_{product}"
        result.first_exclusion_detail = f"排除商品類型：{product}"
        return result
    if result.market not in {"TWSE", "TPEx", "TPEX", "OTC"}:
        result.first_exclusion = "MARKET_UNKNOWN_OR_UNSUPPORTED"
        result.first_exclusion_detail = f"market={result.market!r}"
        return result
    if status == "UNKNOWN":
        result.first_exclusion = "TRADING_STATUS_UNKNOWN"
        result.first_exclusion_detail = "交易狀態未能由官方參照集或明確欄位驗證"
        return result
    if status != "NORMAL":
        result.first_exclusion = f"STATUS_{status}"
        result.first_exclusion_detail = f"交易狀態：{status}"
        return result
    if not SYMBOL_RE.fullmatch(sid) or not result.name:
        result.first_exclusion = "DATA_QUALITY_FAIL"
        result.first_exclusion_detail = "代號或名稱缺失/格式不符"
        return result
    if volume is None:
        result.first_exclusion = "VOLUME_UNKNOWN"
        result.first_exclusion_detail = "最近可得交易日成交量 Cache 不存在或無有效值"
        return result

    result.latest_cache_date = volume.trade_date
    result.volume_shares = volume.volume_shares
    result.volume_lots = volume.volume_lots
    result.volume_source = "cache"
    if volume.volume_lots < threshold:
        result.first_exclusion = "VOLUME_LT_THRESHOLD"
        result.first_exclusion_detail = f"{volume.volume_lots:.3f} 張 < {threshold:g} 張"
        return result
    result.final_stage0_pass = True
    return result


def write_rows(rows: List[AuditRow], csv_path: Optional[Path], json_path: Optional[Path]) -> None:
    if csv_path:
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        import csv
        fields = list(asdict(rows[0]).keys()) if rows else list(AuditRow("", "").__dict__.keys())
        with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader(); w.writerows(asdict(x) for x in rows)
    if json_path:
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps([asdict(x) for x in rows], ensure_ascii=False, indent=2), encoding="utf-8")


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="天機 3K Stage 0 Production Resolver V3")
    p.add_argument("--repo-root")
    p.add_argument("--cache-dir")
    p.add_argument("--universe-json")
    p.add_argument("--volume-threshold", type=float, default=1000.0)
    p.add_argument("--reference-cache")
    p.add_argument("--refresh-reference", action="store_true")
    p.add_argument("--reference-ttl-hours", type=float, default=6.0)
    p.add_argument("--timeout", type=float, default=12.0)
    p.add_argument("--csv")
    p.add_argument("--json")
    p.add_argument("--show-reference-errors", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    repo = Path(args.repo_root).resolve() if args.repo_root else find_repo_root()
    cache_dir = find_cache_dir(repo, args.cache_dir)
    ref_file = Path(args.reference_cache).resolve() if args.reference_cache else repo / "tianji_3k" / "cache" / "reference" / "stage0_reference.json"

    volumes, cache_stats = load_cache_volumes(cache_dir)
    universe = dedupe_universe(load_universe(universe_json=Path(args.universe_json) if args.universe_json else None))
    resolver = OfficialReferenceResolver(ref_file, timeout=args.timeout, ttl_hours=args.reference_ttl_hours,
                                        refresh=args.refresh_reference)
    snap = resolver.build()

    rows = [evaluate_stage0(x, volumes.get(_norm(x.get("symbol") or x.get("stock_id") or x.get("Code"))), resolver, args.volume_threshold)
            for x in universe]

    from collections import Counter
    first = Counter(x.first_exclusion for x in rows)
    products = Counter(x.product_type for x in rows)
    statuses = Counter(x.status for x in rows)
    volume_known = sum(x.volume_lots is not None for x in rows)
    volume_lt = sum(x.volume_lots is not None and x.volume_lots < args.volume_threshold for x in rows)
    volume_ge = sum(x.volume_lots is not None and x.volume_lots >= args.volume_threshold for x in rows)
    passed = sum(x.final_stage0_pass for x in rows)

    print("=" * 72)
    print("天機 3K — Stage 0 Production Audit V3")
    print("=" * 72)
    print(f"Repo root              : {repo}")
    print(f"Universe               : {len(universe):,}")
    print(f"Cache symbols          : {len(volumes):,}")
    print(f"Volume threshold       : {args.volume_threshold:g} 張")
    print(f"Reference cache        : {ref_file}")
    print(f"Reference fetched      : {snap.fetched_at}")
    print("-" * 72)
    print("商品類型")
    for k, v in products.most_common(): print(f"  {k:<22} {v:>6,}")
    print("交易狀態")
    for k, v in statuses.most_common(): print(f"  {k:<22} {v:>6,}")
    print("成交量")
    print(f"  Cache 有效              {volume_known:>6,}")
    print(f"  < 門檻                  {volume_lt:>6,}")
    print(f"  >= 門檻                 {volume_ge:>6,}")
    print(f"  UNKNOWN                 {len(rows)-volume_known:>6,}")
    print("-" * 72)
    print("第一個淘汰/未驗證原因")
    for k, v in first.most_common(): print(f"  {k:<30} {v:>6,}")
    print("-" * 72)
    print(f"Stage 0 PASS（完整驗證） : {passed:,}")
    if args.show_reference_errors and snap.endpoint_errors:
        print("-" * 72)
        print("官方參照 API 錯誤")
        for k, v in snap.endpoint_errors.items(): print(f"  {k}: {v}")

    csv_path = Path(args.csv).resolve() if args.csv else None
    json_path = Path(args.json).resolve() if args.json else None
    write_rows(rows, csv_path, json_path)
    if csv_path: print(f"CSV written             : {csv_path}")
    if json_path: print(f"JSON written            : {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
