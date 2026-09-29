from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

import pandas as pd


REQUIRED = ["date", "stock_id", "Trading_Volume", "open", "max", "min", "close"]
ETF_PREFIXES = ("00",)
# Explicit known ETF / ETN examples; Stage 0 still relies on the project's
# official product-type universe when available. This list is only a cache audit hint.
KNOWN_NON_STOCK = {
    "0050", "0051", "0052", "0053", "0054", "0055", "0056", "0061", "0062",
    "0063", "0064", "0066", "00668", "00669", "00670", "00673", "00675",
    "00676", "00677", "00678", "00679", "00680", "00681", "00682", "00683",
    "00684", "00685", "00686", "00687", "00688", "00689", "00690", "00691",
    "00692", "00693", "00694", "00695", "00696", "00697", "00698", "00699",
    "00700", "00701", "00702", "00703", "00704", "00705", "00706", "00707",
    "00708", "00709", "00710", "00711", "00712", "00713", "00714", "00715",
    "00716", "00717", "00718", "00719", "00720", "00721", "00722", "00723",
    "00724", "00725", "00726", "00727", "00728", "00729", "00730", "00731",
    "00732", "00733", "00734", "00735", "00736", "00737", "00738", "00739",
    "00740", "00741", "00742", "00743", "00744", "00745", "00746", "00747",
    "00748", "00749", "00750", "00751", "00752", "00753", "00754", "00755",
    "00756", "00757", "00758", "00759", "00760", "00762", "00763", "00764",
    "00765", "00766", "00767", "00768", "00769", "00770", "00771", "00772",
    "00773", "00774", "00775", "00776", "00777", "00778", "00779", "00780",
    "00781", "00782", "00783", "00784", "00785", "00786", "00787", "00788",
    "00789", "00790", "00791", "00792", "00793", "00794", "00795", "00796",
    "00797", "00798", "00799",
}


def parse_symbol(path: Path, records) -> str:
    if records:
        s = str(records[0].get("stock_id", "")).strip()
        if s:
            return s
    m = re.search(r"TaiwanStockPrice_(\w+?)_", path.name)
    return m.group(1) if m else path.stem


def audit_file(path: Path) -> dict:
    row = {
        "file": path.name,
        "symbol": "",
        "rows": 0,
        "first_date": "",
        "last_date": "",
        "trading_days": 0,
        "required_columns_ok": False,
        "ohlcv_complete_rows": 0,
        "missing_ohlcv_rows": 0,
        "duplicate_dates": 0,
        "invalid_volume_rows": 0,
        "vma5_possible": False,
        "stage123_possible": False,
        "error": "",
    }
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data = data.get("data", data.get("result", []))
        if not isinstance(data, list):
            raise ValueError("JSON root is not a list")
        row["symbol"] = parse_symbol(path, data)
        df = pd.DataFrame(data)
        row["rows"] = len(df)
        row["required_columns_ok"] = all(c in df.columns for c in REQUIRED)
        if not row["required_columns_ok"]:
            return row

        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        for c in ["Trading_Volume", "open", "max", "min", "close"]:
            df[c] = pd.to_numeric(df[c], errors="coerce")

        df = df.dropna(subset=["date"]).sort_values("date")
        row["trading_days"] = df["date"].nunique()
        if not df.empty:
            row["first_date"] = df["date"].min().date().isoformat()
            row["last_date"] = df["date"].max().date().isoformat()

        row["duplicate_dates"] = int(df["date"].duplicated().sum())
        complete = df[["Trading_Volume", "open", "max", "min", "close"]].notna().all(axis=1)
        row["ohlcv_complete_rows"] = int(complete.sum())
        row["missing_ohlcv_rows"] = int((~complete).sum())
        row["invalid_volume_rows"] = int((df["Trading_Volume"] < 0).fillna(False).sum())

        # Stage 1 needs MA60 and Stage 3 needs 5-day volume.
        row["vma5_possible"] = row["trading_days"] >= 5
        row["stage123_possible"] = row["trading_days"] >= 60 and row["ohlcv_complete_rows"] >= 60
    except Exception as e:
        row["error"] = f"{type(e).__name__}: {e}"
    return row


def main():
    ap = argparse.ArgumentParser(description="Audit Tianji 3K daily JSON cache without external API calls.")
    ap.add_argument("--cache", default=r".\tianji_3k\cache\daily")
    ap.add_argument("--out", default=r".\tianji_3k\cache\daily_cache_audit.csv")
    ap.add_argument("--asof", default="2026-09-18")
    ap.add_argument("--min-volume-lots", type=float, default=500.0)
    args = ap.parse_args()

    cache = Path(args.cache)
    files = sorted(cache.rglob("TaiwanStockPrice_*.json")) if cache.exists() else []
    if not files:
        print(f"[ERROR] 找不到快取：{cache.resolve()}")
        print("請確認你是在 stockcatcher 根目錄執行，且路徑為 .\\tianji_3k\\cache\\daily")
        raise SystemExit(2)

    rows = [audit_file(p) for p in files]
    df = pd.DataFrame(rows)

    df["is_known_etf_hint"] = df["symbol"].astype(str).isin(KNOWN_NON_STOCK)
    df["yesterday_volume_lots"] = pd.NA

    # 依專案規格，前一交易日成交量 < 500 張排除。
    for i, r in df.iterrows():
        p = cache / str(r["file"])
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            x = pd.DataFrame(data)
            x["date"] = pd.to_datetime(x["date"], errors="coerce")
            x["Trading_Volume"] = pd.to_numeric(x["Trading_Volume"], errors="coerce")
            x = x.dropna(subset=["date"]).sort_values("date")
            if len(x) >= 2:
                df.loc[i, "yesterday_volume_lots"] = float(x.iloc[-2]["Trading_Volume"]) / 1000.0
        except Exception:
            pass

    df["stage0_liquidity_hint"] = (
        (df["stage123_possible"] == True)
        & (df["yesterday_volume_lots"].fillna(-1).astype(float) >= args.min_volume_lots)
        & (df["is_known_etf_hint"] == False)
        & (df["error"] == "")
    )

    # Ground-truth 2026-09-18 regression check: evaluate Stage 1-3 from cache only.
    target = pd.Timestamp(args.asof)
    gt = []
    for _, r in df.iterrows():
        if r["error"] or not r["stage123_possible"]:
            continue
        p = cache / str(r["file"])
        try:
            x = pd.DataFrame(json.loads(p.read_text(encoding="utf-8")))
            x["date"] = pd.to_datetime(x["date"], errors="coerce")
            for c in ["Trading_Volume", "open", "max", "min", "close"]:
                x[c] = pd.to_numeric(x[c], errors="coerce")
            x = x.dropna(subset=["date"]).sort_values("date")
            x = x[x["date"] <= target].copy()
            if len(x) < 60:
                continue
            x["ma20"] = x["close"].rolling(20).mean()
            x["ma60"] = x["close"].rolling(60).mean()
            x["vma5"] = x["Trading_Volume"].rolling(5).mean()
            if len(x) < 3:
                continue
            k0, k1, k2 = x.iloc[-1], x.iloc[-2], x.iloc[-3]
            stage1 = (
                k0["close"] > k0["ma20"] and
                k0["close"] > k0["ma60"] and
                k0["ma20"] > k0["ma60"] and
                k0["ma20"] > k1["ma20"]
            )
            gain = (k0["close"] / k0["open"] - 1.0) if k0["open"] else -999
            stage2 = (
                k0["close"] > k0["open"] and
                gain >= 0.04 and
                k0["max"] > k1["max"] and
                k0["max"] > k2["max"] and
                k0["close"] > max(k1["max"], k2["max"])
            )
            vma5_lots = k0["vma5"] / 1000.0
            today_lots = k0["Trading_Volume"] / 1000.0
            yesterday_lots = k1["Trading_Volume"] / 1000.0
            stage3 = (
                vma5_lots >= 1000.0 and
                today_lots > yesterday_lots and
                today_lots / vma5_lots >= 1.5
            )
            gt.append({
                "symbol": r["symbol"],
                "stage1": bool(stage1),
                "stage2": bool(stage2),
                "stage3": bool(stage3),
                "3k_pass": bool(stage1 and stage2 and stage3),
                "close": float(k0["close"]),
                "gain_pct": float(gain * 100),
                "vma5_lots": float(vma5_lots),
                "today_volume_lots": float(today_lots),
                "yesterday_volume_lots": float(yesterday_lots),
            })
        except Exception:
            continue

    gt_df = pd.DataFrame(gt)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False, encoding="utf-8-sig")
    gt_out = out.with_name(out.stem + "_20260918.csv")
    gt_df.to_csv(gt_out, index=False, encoding="utf-8-sig")

    print("\n===== 天機 3K Cache Audit =====")
    print(f"cache       : {cache.resolve()}")
    print(f"files       : {len(df)}")
    print(f"symbols     : {df['symbol'].nunique()}")
    print(f"known ETF hint : {int(df['is_known_etf_hint'].sum())}")
    print(f">=60 days   : {int(df['stage123_possible'].sum())}")
    print(f"missing OHLCV rows files : {int((df['missing_ohlcv_rows'] > 0).sum())}")
    print(f"yesterday >=500 lots : {int((df['yesterday_volume_lots'].fillna(-1).astype(float) >= args.min_volume_lots).sum())}")
    print(f"Stage0 liquidity hint : {int(df['stage0_liquidity_hint'].sum())}")

    if not gt_df.empty:
        print("\n--- 2026-09-18 cache-only Stage 1-3 regression ---")
        print(f"Stage1 PASS : {int(gt_df['stage1'].sum())}")
        print(f"Stage2 PASS : {int(gt_df['stage2'].sum())}")
        print(f"Stage3 PASS : {int(gt_df['stage3'].sum())}")
        print(f"3K PASS     : {int(gt_df['3k_pass'].sum())}")
        print("\n3K PASS symbols:")
        print(", ".join(gt_df.loc[gt_df["3k_pass"], "symbol"].astype(str).tolist()) or "(none)")

    print(f"\n詳細報表: {out.resolve()}")
    print(f"回歸報表: {gt_out.resolve()}")


if __name__ == "__main__":
    main()
