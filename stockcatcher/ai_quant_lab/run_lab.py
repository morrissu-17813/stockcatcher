"""CLI entry point for the isolated Tianji AI Quant Lab."""
from __future__ import annotations
import argparse, json, uuid
from datetime import datetime
from pathlib import Path
from engine import LabEngine, ROOT
DATA_DIR = ROOT / "data"
from event_adapter.production_reader import iter_production_events


def now(): return datetime.now().astimezone().isoformat(timespec="seconds")
def main():
    parser = argparse.ArgumentParser(description="Tianji AI Quant Lab — isolated paper-only engine")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="show current engine and ledger state")
    demo = sub.add_parser("demo", help="run safe paper-only example events")
    demo.add_argument("--symbol", default="2330")
    demo.add_argument("--price", default="100")
    demo.add_argument("--quantity", type=int, default=100)
    ingest = sub.add_parser("ingest", help="process events from a Lab-owned JSONL file")
    ingest.add_argument("path")
    sync = sub.add_parser("sync-production", help="preview or ingest real Tianji 3K ledger events from read-only source")
    sync.add_argument("source_root", help="production data root containing predictions/ and/or validation/")
    sync.add_argument("--since", default=None, help="include events on/after YYYY-MM-DD")
    sync.add_argument("--ingest", action="store_true", help="process the read-only source events directly; durable persistence requires Supabase credentials")
    report = sub.add_parser("report", help="generate daily JSON and Markdown report")
    report.add_argument("--date", default=None)
    args = parser.parse_args()
    engine = LabEngine()
    if args.command == "status":
        print(json.dumps(engine.state(), ensure_ascii=False, indent=2))
    elif args.command == "demo":
        event = {"event_id": str(uuid.uuid4()), "event_type": "signal.created", "occurred_at": now(), "source": "lab-demo", "payload": {"mode": "paper", "symbol": args.symbol, "side": "BUY", "quantity": args.quantity, "price": args.price}}
        print(json.dumps(engine.process(event), ensure_ascii=False, indent=2))
        print(f"Persistence: {'supabase' if engine.store.configured else 'memory-only-dev (no local database or file persistence)'}")
    elif args.command == "ingest":
        print(json.dumps(engine.ingest_jsonl(args.path), ensure_ascii=False, indent=2))
    elif args.command == "sync-production":
        events = list(iter_production_events(args.source_root, since=args.since))
        preview = [{"event_id": e["event_id"], "event_type": e["event_type"], "occurred_at": e["occurred_at"], "symbol": (e.get("payload") or {}).get("symbol"), "prediction_id": (e.get("payload") or {}).get("prediction_id"), "source": e["source"]} for e in events[:20]]
        result = {"source_root": str(Path(args.source_root).expanduser().resolve()), "source_read_only": True, "candidate_events": len(events), "preview_first_20": preview, "local_files_written": False, "ingested": 0, "persistence": "supabase" if engine.store.configured else "memory-only-dev"}
        if args.ingest:
            outcomes = [engine.process(event) for event in events]
            result["ingested"] = len(outcomes)
            result["ingest_status_counts"] = {status: sum(1 for x in outcomes if x.get("status") == status) for status in sorted({x.get("status", "unknown") for x in outcomes})}
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.command == "report":
        print(engine.generate_report(args.date))

if __name__ == "__main__": main()
