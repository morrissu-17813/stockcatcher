"""CLI: reproduce the Tianji 3K pipeline from an archived GitHub Actions LOG."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from log_replay import TianjiLogReplay, ReplayConfig, write_replay_outputs


def main() -> int:
    ap = argparse.ArgumentParser(description="Offline paper-only replay of a Tianji 3K production LOG/ZIP")
    ap.add_argument("--log", required=True, help="Path to LOG .txt or ZIP export (read-only)")
    ap.add_argument("--out", default="reports/offline_replay", help="Output directory")
    ap.add_argument("--starting-cash", default="1000000")
    ap.add_argument("--max-order-notional", default="100000")
    ap.add_argument("--max-positions", type=int, default=3)
    ap.add_argument("--min-projected-ratio", default="2.3")
    ap.add_argument("--slippage-bps", default="10")
    args = ap.parse_args()
    cfg = ReplayConfig(starting_cash=args.starting_cash, max_order_notional=args.max_order_notional,
                       max_positions=args.max_positions, min_projected_volume_ratio=args.min_projected_ratio,
                       slippage_bps=args.slippage_bps)
    report = TianjiLogReplay(cfg).run(args.log)
    paths = write_replay_outputs(report, args.out)
    print(json.dumps({"ok": True, "trade_date": report["source"]["trade_date"],
                      "metrics": report["pipeline"]["intraday"], "simulation": report["simulation"],
                      "close_audit": report["pipeline"]["close"], "outputs": paths}, ensure_ascii=False, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
