"""天機 3K — 全市場 Stage 0 模擬器 / Audit Tool.

用途
----
不呼叫 FinMind，使用現有 StockUniverseProvider（若可匯入）取得 Universe，
再以 tianji_3k/cache/daily 下既有日線 cache 覆蓋最近交易日成交量，依照
Stage 0 固定排除順序逐層統計：

1. Product Type
2. Market
3. Trading Status / Disposal / Suspended
4. Data Quality
5. Yesterday Volume threshold

預設成交量門檻為 1,000 張，可用 --volume-threshold 修改。

重要：本工具不會把「未知」偷偷當成「正常」。若現有 Universe 沒有獨立商品類型或交易狀態來源，
會在報告中列為 UNKNOWN/UNVERIFIED；可用 --trust-universe-fields 明確要求信任 Universe 已提供的欄位。
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import re
import sys
from collections import Counter
from dataclasses import dataclass, asdict
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

LOG = logging.getLogger("stage0_audit")
SYMBOL_RE = re.compile(r"^\d{4}$")
MARKETS = {"TWSE", "TPEx", "TPEX", "OTC", "TSE"}

PRODUCT_FLAG_MAP = {
    "is_etf": "ETF",
    "is_etn": "ETN",
    "is_warrant": "WARRANT",
    "is_preferred_stock": "PREFERRED",
    "is_bond": "BOND",
    "is_dr": "DR",
    "is_emerging": "EMERGING",
}

PRODUCT_TEXT_MAP = {
    "etf": "ETF", "exchange traded fund": "ETF",
    "etn": "ETN", "exchange traded note": "ETN",
    "warrant": "WARRANT", "權證": "WARRANT",
    "preferred": "PREFERRED", "特別股": "PREFERRED", "優先股": "PREFERRED",
    "bond": "BOND", "債券": "BOND",
    "dr": "DR", "存託憑證": "DR",
    "emerging": "EMERGING", "興櫃": "EMERGING",
    "common_stock": "COMMON_STOCK", "common stock": "COMMON_STOCK", "ordinary_share": "COMMON_STOCK",
    "ordinary shares": "COMMON_STOCK", "stock": "COMMON_STOCK", "普通股": "COMMON_STOCK",
}

STATUS_FLAG_MAP = {
    "is_disposal": "DISPOSAL",
    "is_suspended": "SUSPENDED",
    "abnormal_status": "ABNORMAL",
}

@dataclass
class CacheVolume:
    symbol: str
    trade_date: str
    volume_shares: float
    volume_lots: float
    source_file: str

@dataclass
class AuditRow:
    symbol: str
    name: str = ""
    market: str = ""
    product_type: str = "UNKNOWN"
    product_source: str = "unavailable"
    status: str = "UNKNOWN"
    status_source: str = "unavailable"
    latest_cache_date: str = ""
    volume_shares: Optional[float] = None
    volume_lots: Optional[float] = None
    volume_source: str = "unavailable"
    first_exclusion: str = ""
    first_exclusion_detail: str = ""
    final_stage0_pass: bool = False


def _norm(v: Any) -> str:
    return str(v).strip() if v is not None else ""


def _bool(v: Any) -> Optional[bool]:
    if isinstance(v, bool):
        return v
    if v is None:
        return None
    s = str(v).strip().lower()
    if s in {"1", "true", "yes", "y", "是", "正常"}:
        return True
    if s in {"0", "false", "no", "n", "否"}:
        return False
    return None


def _num(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _date_key(v: Any) -> Optional[str]:
    s = _norm(v)
    if not s:
        return None
    s = s.replace("/", "-")
    for fmt in ("%Y-%m-%d", "%Y%m%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(s).date().isoformat()
    except ValueError:
        return None


def find_repo_root(start: Optional[Path] = None) -> Path:
    p = (start or Path(__file__)).resolve()
    if p.is_file():
        p = p.parent
    for candidate in [p, *p.parents]:
        if (candidate / "tianji_3k").is_dir() and ((candidate / ".env").exists() or (candidate / "scanner.py").exists()):
            return candidate
    # Installed inside repo: tools/ -> tianji_3k/ -> repo root.
    return Path(__file__).resolve().parents[2]


def find_cache_dir(repo_root: Path, explicit: Optional[str]) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    return repo_root / "tianji_3k" / "cache" / "daily"


def load_cache_volumes(cache_dir: Path) -> Tuple[Dict[str, CacheVolume], Dict[str, int]]:
    """Scan all daily cache JSON files and keep latest valid row per symbol."""
    latest: Dict[str, CacheVolume] = {}
    stats = Counter(files=0, rows=0, valid_rows=0, bad_files=0, bad_rows=0)
    if not cache_dir.exists():
        return latest, dict(stats)

    for path in sorted(cache_dir.glob("*.json")):
        stats["files"] += 1
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception:
            stats["bad_files"] += 1
            continue
        rows = payload if isinstance(payload, list) else payload.get("data", []) if isinstance(payload, dict) else []
        if not isinstance(rows, list):
            stats["bad_files"] += 1
            continue
        for row in rows:
            stats["rows"] += 1
            if not isinstance(row, dict):
                stats["bad_rows"] += 1
                continue
            symbol = _norm(row.get("stock_id") or row.get("symbol") or row.get("Code"))
            d = _date_key(row.get("date") or row.get("Date") or row.get("trade_date"))
            vol = _num(row.get("Trading_Volume") if "Trading_Volume" in row else row.get("volume_shares", row.get("volume")))
            if not SYMBOL_RE.fullmatch(symbol) or not d or vol is None or vol < 0:
                stats["bad_rows"] += 1
                continue
            stats["valid_rows"] += 1
            item = CacheVolume(symbol, d, vol, vol / 1000.0, path.name)
            old = latest.get(symbol)
            if old is None or item.trade_date > old.trade_date:
                latest[symbol] = item
    return latest, dict(stats)


def load_universe(provider: Optional[Any] = None, universe_json: Optional[Path] = None) -> List[Dict[str, Any]]:
    if universe_json:
        payload = json.loads(universe_json.read_text(encoding="utf-8-sig"))
        if isinstance(payload, dict):
            payload = payload.get("rows", payload.get("data", []))
        if not isinstance(payload, list):
            raise ValueError("Universe JSON 必須是 list，或 {rows:[...]} / {data:[...]}。")
        return [x for x in payload if isinstance(x, dict)]

    if provider is None:
        try:
            from tianji_3k.data.stock_universe import StockUniverseProvider
            provider = StockUniverseProvider()
        except Exception as exc:
            raise RuntimeError(f"無法載入 StockUniverseProvider：{exc}") from exc
    rows = provider.fetch()
    if not isinstance(rows, list):
        raise RuntimeError("StockUniverseProvider.fetch() 未回傳 list。")
    return [x for x in rows if isinstance(x, dict)]


def dedupe_universe(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    merged: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        sid = _norm(row.get("symbol") or row.get("stock_id") or row.get("Code"))
        if not sid:
            continue
        if sid not in merged:
            merged[sid] = dict(row)
        else:
            # Preserve any richer fields supplied by another source.
            for k, v in row.items():
                if k not in merged[sid] or merged[sid][k] in (None, "", False):
                    merged[sid][k] = v
    return list(merged.values())


def classify_product(row: Dict[str, Any], trust_universe_fields: bool) -> Tuple[str, str]:
    """Classify instrument type without silently treating missing data as common stock."""
    for key, label in PRODUCT_FLAG_MAP.items():
        if key in row:
            val = _bool(row.get(key))
            if val is True:
                return label, f"field:{key}"
            if val is False and label != "EMERGING":
                continue
    if "is_common_stock" in row and _bool(row.get("is_common_stock")) is True:
        return "COMMON_STOCK", "field:is_common_stock"

    for key in ("product_type", "instrument_type", "security_type", "securityType", "type"):
        if key not in row:
            continue
        raw_original = _norm(row.get(key))
        raw = raw_original.lower()
        label = PRODUCT_TEXT_MAP.get(raw)
        if label is None:
            for needle, mapped in PRODUCT_TEXT_MAP.items():
                if needle in raw:
                    label = mapped
                    break
        if label is None:
            continue
        if label == "COMMON_STOCK" and not trust_universe_fields and key in {"security_type", "securityType", "type"}:
            return "UNKNOWN", f"{key}_requires_trust"
        return label, f"field:{key}"
    return "UNKNOWN", "unavailable"

def classify_status(row: Dict[str, Any]) -> Tuple[str, str]:
    found = False
    for key, label in STATUS_FLAG_MAP.items():
        if key not in row:
            continue
        found = True
        val = _bool(row.get(key))
        if val is True:
            return label, f"field:{key}"
    for key in ("status", "trading_status", "trade_status", "TradingStatus"):
        if key not in row:
            continue
        found = True
        raw = _norm(row.get(key)).lower()
        if any(x in raw for x in ("disposal", "處置")):
            return "DISPOSAL", f"field:{key}"
        if any(x in raw for x in ("suspend", "停牌", "停止交易")):
            return "SUSPENDED", f"field:{key}"
        if raw and raw not in {"normal", "正常", "trading", "上市", "上櫃", "1"}:
            return "ABNORMAL", f"field:{key}"
    return ("NORMAL", "explicit_fields") if found else ("UNKNOWN", "unavailable")


def market_value(row: Dict[str, Any]) -> str:
    raw = _norm(row.get("market") or row.get("exchange") or row.get("market_type"))
    up = raw.upper()
    if up in {"TSE", "TWSE"}:
        return "TWSE"
    if up in {"OTC", "TPEX", "TPEX"}:
        return "TPEx"
    return raw


def audit_rows(
    universe: List[Dict[str, Any]],
    volumes: Dict[str, CacheVolume],
    volume_threshold: float,
    trust_universe_fields: bool,
    allow_universe_volume_fallback: bool = False,
) -> List[AuditRow]:
    """Run sequential Stage 0 audit. Missing values stay UNKNOWN, never zero/normal."""
    out: List[AuditRow] = []
    for raw in universe:
        sid = _norm(raw.get("symbol") or raw.get("stock_id") or raw.get("Code"))
        name = _norm(raw.get("name") or raw.get("Name") or raw.get("CompanyName"))
        market = market_value(raw)
        product, product_source = classify_product(raw, trust_universe_fields)
        status, status_source = classify_status(raw)

        cv = volumes.get(sid)
        if cv is not None:
            vol_lots = cv.volume_lots
            vol_shares = cv.volume_shares
            vol_source = "cache"
        elif allow_universe_volume_fallback:
            fallback = _num(raw.get("previous_volume_lots"))
            # The current StockUniverseProvider maps missing API values to 0.0.
            # Treat that synthetic zero as UNKNOWN unless the caller explicitly supplied
            # a non-zero value. This prevents "missing" from becoming "0 lots".
            if fallback is not None and fallback > 0:
                vol_lots = fallback
                vol_shares = fallback * 1000
                vol_source = "universe_previous_volume"
            else:
                vol_lots = None
                vol_shares = None
                vol_source = "unavailable"
        else:
            vol_lots = None
            vol_shares = None
            vol_source = "unavailable"

        first = ""
        detail = ""
        # Fixed Stage 0 exclusion order. UNKNOWN is an unresolved state, not PASS.
        if product == "UNKNOWN":
            first, detail = "PRODUCT_TYPE_UNKNOWN", product_source
        elif product != "COMMON_STOCK":
            first, detail = "PRODUCT_TYPE", product
        elif market not in {"TWSE", "TPEx"}:
            first, detail = "MARKET", market or "missing"
        elif status == "UNKNOWN":
            first, detail = "STATUS_UNKNOWN", status_source
        elif status != "NORMAL":
            first, detail = "STATUS", status
        elif not SYMBOL_RE.fullmatch(sid):
            first, detail = "DATA_QUALITY", "symbol must be 4 digits"
        elif vol_lots is None:
            first, detail = "DATA_QUALITY", "recent volume unavailable"
        elif vol_lots < volume_threshold:
            first, detail = "YESTERDAY_VOLUME", f"{vol_lots:.2f} < {volume_threshold:.2f} lots"

        out.append(AuditRow(
            symbol=sid, name=name, market=market, product_type=product,
            product_source=product_source, status=status, status_source=status_source,
            latest_cache_date=cv.trade_date if cv else "",
            volume_shares=vol_shares, volume_lots=vol_lots, volume_source=vol_source,
            first_exclusion=first, first_exclusion_detail=detail,
            final_stage0_pass=(first == ""),
        ))
    return out

def summary(rows: List[AuditRow], volume_threshold: float = 1000.0) -> Dict[str, Any]:
    n = len(rows)
    remaining = n
    layers = []
    for code, label in [
        ("PRODUCT_TYPE", "商品類型"),
        ("MARKET", "市場"),
        ("STATUS", "交易狀態"),
        ("DATA_QUALITY", "資料品質"),
        ("YESTERDAY_VOLUME", "昨日成交量"),
    ]:
        eliminated = sum(r.first_exclusion == code for r in rows)
        remaining -= eliminated
        layers.append({"code": code, "label": label, "eliminated": eliminated, "remaining": remaining})
    return {
        "universe": n,
        "stage0_pass": sum(r.final_stage0_pass for r in rows),
        "unknown_product": sum(r.product_type == "UNKNOWN" for r in rows),
        "unknown_status": sum(r.status == "UNKNOWN" for r in rows),
        "volume_cache": sum(r.volume_source == "cache" for r in rows),
        "volume_unavailable": sum(r.volume_lots is None for r in rows),
        "volume_lt_threshold": sum(r.volume_lots is not None and r.volume_lots < volume_threshold for r in rows),
        "volume_ge_threshold": sum(r.volume_lots is not None and r.volume_lots >= volume_threshold for r in rows),
        "layers": layers,
        "unknown_first_exclusion": dict(Counter(r.first_exclusion for r in rows if r.first_exclusion.endswith("_UNKNOWN"))),
    }

def write_csv(rows: List[AuditRow], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(asdict(rows[0]).keys()) if rows else list(AuditRow("0000").__dict__.keys()))
        w.writeheader()
        for r in rows:
            w.writerow(asdict(r))


def print_report(
    rows: List[AuditRow], cache_stats: Dict[str, int], cache_dir: Path,
    threshold: float, repo_root: Path, trust: bool,
    cache_volumes: Dict[str, CacheVolume], allow_universe_volume_fallback: bool,
) -> None:
    s = summary(rows, threshold)
    print("=" * 72)
    print("天機 3K — 全市場 Stage 0 Audit V2")
    print("=" * 72)
    print(f"Repo root              : {repo_root}")
    print(f"Universe                : {s['universe']:,}")
    print(f"Cache                   : {cache_dir}")
    print(f"Cache files             : {cache_stats.get('files',0):,}")
    print(f"Cache symbols           : {len(cache_volumes):,}")
    print(f"Volume threshold        : {threshold:,.0f} 張")
    print(f"Trust Universe fields   : {trust}")
    print(f"Universe volume fallback: {allow_universe_volume_fallback}")
    print()
    print("固定排除順序（UNKNOWN 不視為 PASS；每檔只計入第一個淘汰/未驗證原因）")
    print("-" * 72)
    for layer in s["layers"]:
        print(f"{layer['label']:<10} 排除 {layer['eliminated']:>5,}  → 剩餘 {layer['remaining']:>5,}")
    print("-" * 72)
    print(f"Stage 0 PASS（已驗證） : {s['stage0_pass']:,}")
    print(f"商品類型 UNKNOWN        : {s['unknown_product']:,}")
    print(f"交易狀態 UNKNOWN        : {s['unknown_status']:,}")
    print(f"成交量有 Cache          : {s['volume_cache']:,}")
    print(f"成交量 UNKNOWN          : {s['volume_unavailable']:,}")
    if s["unknown_first_exclusion"]:
        print(f"未驗證首要原因         : {s['unknown_first_exclusion']}")

    vol_rows = [r for r in rows if r.volume_lots is not None]
    under = [r for r in vol_rows if r.volume_lots < threshold]
    over = [r for r in vol_rows if r.volume_lots >= threshold]
    print()
    print(f"【最近可得交易日成交量 < {threshold:,.0f} 張】")
    print(f"可計算筆數              : {len(vol_rows):,}")
    print(f"低於門檻                : {len(under):,}")
    print(f"達到門檻                : {len(over):,}")
    print(f"成交量 UNKNOWN          : {len(rows)-len(vol_rows):,}")
    print("前 20 筆低量股票：")
    for r in sorted(under, key=lambda x: (x.volume_lots, x.symbol))[:20]:
        print(f"  {r.symbol} {r.name:<10} {r.volume_lots:>10.1f} 張  {r.latest_cache_date or '-'}  [{r.volume_source}]")
    print("=" * 72)

def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="天機 3K 全市場 Stage 0 模擬器")
    ap.add_argument("--repo-root", help="stockcatcher repo root")
    ap.add_argument("--cache-dir", help="daily cache directory")
    ap.add_argument("--universe-json", type=Path, help="離線 Universe JSON；可為 list 或 {rows:[...]}")
    ap.add_argument("--volume-threshold", type=float, default=1000.0, help="昨日成交量門檻（張），預設 1000")
    ap.add_argument("--trust-universe-fields", action="store_true",
                    help="信任 Universe 的 security_type/product/status 欄位；否則缺乏獨立來源時標為 UNKNOWN")
    ap.add_argument("--allow-universe-volume-fallback", action="store_true",
                    help="Cache 沒有成交量時，允許使用 Universe.previous_volume_lots；預設關閉，避免缺值被誤判")
    ap.add_argument("--csv", type=Path, help="輸出逐檔 audit CSV")
    ap.add_argument("--json", type=Path, help="輸出 summary + rows JSON")
    ap.add_argument("--log-level", default="WARNING", choices=["DEBUG","INFO","WARNING","ERROR"])
    args = ap.parse_args(argv)
    logging.basicConfig(level=getattr(logging, args.log_level), format="%(levelname)s %(message)s")

    repo_root = Path(args.repo_root).expanduser().resolve() if args.repo_root else find_repo_root()
    cache_dir = find_cache_dir(repo_root, args.cache_dir)
    try:
        volumes, cache_stats = load_cache_volumes(cache_dir)
        universe = dedupe_universe(load_universe(universe_json=args.universe_json))
        rows = audit_rows(
            universe, volumes, args.volume_threshold, args.trust_universe_fields,
            allow_universe_volume_fallback=args.allow_universe_volume_fallback,
        )
    except Exception as exc:
        LOG.error("Stage 0 audit failed: %s", exc)
        return 2

    print_report(
        rows, cache_stats, cache_dir, args.volume_threshold, repo_root,
        args.trust_universe_fields, volumes, args.allow_universe_volume_fallback,
    )
    if args.csv:
        write_csv(rows, args.csv)
        print(f"CSV written             : {args.csv.resolve()}")
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        payload = {"summary": summary(rows, args.volume_threshold), "cache_stats": cache_stats,
                   "volume_threshold_lots": args.volume_threshold,
                   "allow_universe_volume_fallback": args.allow_universe_volume_fallback,
                   "rows": [asdict(r) for r in rows]}
        args.json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"JSON written            : {args.json.resolve()}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
