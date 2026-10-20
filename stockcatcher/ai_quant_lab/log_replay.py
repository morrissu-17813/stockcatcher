"""Offline replay of real Tianji 3K production runner logs.

This module only reads source logs and creates isolated simulated trades. It never
imports broker APIs, writes into Tianji 3K production data, or calls Supabase.
The replay deliberately distinguishes a verified execution observation from a
watchlist's displayed price, whose quote freshness is not represented in these logs.
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
import zipfile
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, time, timezone, timedelta
from decimal import Decimal, ROUND_FLOOR
from pathlib import Path
from typing import Any, Iterable
from intraday_execution import EntryPolicy, EntryContext, evaluate_entry, size_position

TAIPEI = timezone(timedelta(hours=8))
UTC = timezone.utc

GITHUB_LINE = re.compile(r"^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?Z)\s+(.*)$")
ANSI = re.compile(r"\x1b\[[0-9;]*m")
NUMBER = r"[-+]?(?:\d[\d,]*\.?\d*|\.\d+)"
WATCH_ROW = re.compile(
    r"^\s*(?P<symbol>\d{4})\s+(?P<name>.+?)\s+(?P<bucket>PREMARKET|DYNAMIC)\s+"
    r"(?P<market>TWSE|TPEx)\s+(?P<price>--|[\d,]+(?:\.\d+)?)(?P<flag>!)?\s*"
    r"(?P<status>WATCHING|BREAKOUT_PENDING|COOLDOWN|INVALIDATED|TRIGGERED)\s*$"
)
TRIGGER = re.compile(
    rf"BREAKOUT TRIGGER\s*\|\s*(\d{{4}})\s+([^|]+?)\s*\|\s*price=({NUMBER})\s*\|\s*breakout=({NUMBER})"
)
PREDICTION = re.compile(r"(?:INTRADAY|DAY)_3K_PREDICTION\s*\|\s*(\d{4})\s*\|\s*level=([A-Z_]+)\s*\|\s*evidence=([A-Z0-9_]+)")
CANDIDATE = re.compile(rf"DYNAMIC CANDIDATE\s*\|\s*(\d{{4}})\s+([^|]+?)\s*\|\s*({NUMBER})%\s*\|\s*Breakout=({NUMBER})\s*\|\s*VMA5=({NUMBER})張")
RADAR = re.compile(r"TIANJI 3K RADAR\s*\|\s*(\d\d:\d\d:\d\d)\s*\|\s*監控中\s*(\d+)\s*檔\s*\|\s*MIS 回傳\s*(\d+)\s*檔")
POOL_LINE = re.compile(rf"^\s*(\d{{4}})\s+({NUMBER})\s+({NUMBER})\s+({NUMBER})\s+({NUMBER})\s*$")


def _dec(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value).replace(",", "").replace("+", "").replace("x", ""))
    except Exception:
        return None


def _num(value: Any) -> float | None:
    d = _dec(value)
    return float(d) if d is not None else None


def _load_log(source: str | Path) -> tuple[str, str]:
    """Load a .txt or ZIP export without extracting arbitrary ZIP paths."""
    p = Path(source).expanduser().resolve()
    if not p.exists():
        raise FileNotFoundError(f"LOG 檔案不存在：{p}")
    if p.suffix.lower() == ".zip":
        with zipfile.ZipFile(p) as zf:
            candidates = [i for i in zf.infolist() if not i.is_dir() and i.filename.lower().endswith(".txt")]
            candidates = [i for i in candidates if "system.txt" not in i.filename.lower()]
            if not candidates:
                raise ValueError("ZIP 裡找不到可用的 runner LOG .txt 檔")
            item = max(candidates, key=lambda i: i.file_size)
            raw = zf.read(item)
            member = item.filename
    else:
        raw = p.read_bytes()
        member = p.name
    try:
        return raw.decode("utf-8-sig", errors="replace"), member
    except Exception as exc:
        raise ValueError(f"無法讀取 LOG 文字：{exc}") from exc


def _timestamp(outer_stamp: str | None) -> str | None:
    if not outer_stamp:
        return None
    try:
        dt = datetime.fromisoformat(outer_stamp.replace("Z", "+00:00"))
        return dt.astimezone(TAIPEI).isoformat(timespec="milliseconds")
    except ValueError:
        return None


def _extract_values(content: str) -> dict[str, str]:
    return {k: v.rstrip(",") for k, v in re.findall(r"([A-Za-z_][A-Za-z0-9_]*)=([^\s|]+)", content)}


@dataclass
class ReplayConfig:
    starting_cash: str = "1000000"
    max_order_notional: str = "100000"
    max_positions: int = 3
    commission_rate: str = "0.001425"
    sell_tax_rate: str = "0.003"
    slippage_bps: str = "10"
    min_projected_volume_ratio: str = "2.3"
    max_trigger_age_seconds: float = 300.0
    max_snapshot_received_age_seconds: float = 30.0
    stop_loss_pct: str = "0.02"
    take_profit_pct: str = "0.04"
    entry_cutoff_taipei: str = "13:20:00"


class TianjiLogReplay:
    def __init__(self, config: ReplayConfig | None = None):
        self.config = config or ReplayConfig()

    def run(self, source: str | Path) -> dict[str, Any]:
        text, member = _load_log(source)
        source_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        lines = text.splitlines()
        events: list[dict[str, Any]] = []
        quotes: list[dict[str, Any]] = []
        candidates: list[dict[str, Any]] = []
        triggers: list[dict[str, Any]] = []
        predictions: list[dict[str, Any]] = []
        notifications: list[dict[str, Any]] = []
        fetch_metrics: list[dict[str, Any]] = []
        intervals: list[float] = []
        warnings: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        stage: dict[str, Any] = {}
        radar_cycles: list[dict[str, Any]] = []
        phases: list[dict[str, Any]] = []
        pool_read = False
        pool_expected = 0
        stage_context: int | None = None

        for lineno, raw in enumerate(lines, start=1):
            outer = GITHUB_LINE.match(raw)
            stamp = outer.group(1) if outer else None
            content = ANSI.sub("", outer.group(2) if outer else raw).strip()
            at = _timestamp(stamp)
            if not content:
                continue

            # Stage summaries from the premarket scan. PASS/FAIL lines are contextual,
            # so first infer which stage banner has most recently appeared.
            banner = re.search(r"Stage ([0-3]) (?:Production Audit|Trend Engine|Breakout Engine|Volume Engine)", content, re.I)
            if banner:
                stage_context = int(banner.group(1))
            m = re.search(r"Stage 0 PASS(?:（完整驗證）)?\s*:\s*(\d+)", content)
            if m: stage["stage0_pass_complete"] = int(m.group(1))
            m = re.search(r"Stage 0 PASS input\s*:\s*(\d+)", content, re.I)
            if m: stage["stage0_pass_input_to_stage1"] = int(m.group(1))
            m = re.search(r"Stage 1 PASS input\s*:\s*(\d+)", content, re.I)
            if m: stage["stage1_pass_input_to_stage2"] = int(m.group(1))
            m = re.search(r"Stage 2 PASS input\s*:\s*(\d+)", content, re.I)
            if m: stage["stage2_pass_input_to_stage3"] = int(m.group(1))
            m = re.search(r"^PASS\s*:\s*(\d+)", content)
            if m:
                stage[f"stage{stage_context}_pass"] = int(m.group(1)) if stage_context is not None else int(m.group(1))
            m = re.search(r"^FAIL/UNKNOWN\s*:\s*(\d+)", content)
            if m and stage_context is not None:
                stage[f"stage{stage_context}_fail_unknown"] = int(m.group(1))
            m = re.search(r"3K PASS\s*:\s*(\d+)", content)
            if m:
                stage["premarket_3k_pass"] = int(m.group(1))
                pool_expected = int(m.group(1)); pool_read = True; stage["premarket_pool"] = []
                continue
            if pool_read and pool_expected > 0:
                pm = POOL_LINE.match(content)
                if pm:
                    stage.setdefault("premarket_pool", []).append({"symbol": pm.group(1), "raw_values": [pm.group(i) for i in range(2, 6)], "source_line": lineno})
                    if len(stage["premarket_pool"]) >= pool_expected: pool_read = False
                elif content.startswith("JSON written") or content.startswith("CSV written"):
                    pool_read = False

            m = RADAR.search(content)
            if m:
                row = {"timestamp": at, "inner_time_taipei": m.group(1), "monitoring_symbols": int(m.group(2)), "mis_returned_symbols": int(m.group(3)), "source_line": lineno}
                radar_cycles.append(row)
                events.append({"event_type": "radar_cycle", **row})

            if "PREMARKET=" in content and "DYNAMIC=" in content and "TOTAL=" in content:
                m = re.search(r"PREMARKET=(\d+)\s*\|\s*DYNAMIC=(\d+)\s*\|\s*TOTAL=(\d+)", content)
                if m:
                    events.append({"event_type": "pool_size", "timestamp": at, "premarket": int(m.group(1)), "dynamic": int(m.group(2)), "total": int(m.group(3)), "source_line": lineno})

            m = TRIGGER.search(content)
            if m:
                trigger = {"event_type": "breakout_trigger", "timestamp": at, "symbol": m.group(1), "name": m.group(2).strip(), "price": _num(m.group(3)), "breakout_price": _num(m.group(4)), "source_line": lineno}
                triggers.append(trigger); events.append(trigger)

            m = PREDICTION.search(content)
            if m:
                symbol, level, evidence = m.groups()
                vals = _extract_values(content)
                pred = {
                    "event_type": "prediction", "timestamp": at, "symbol": symbol,
                    "level": level, "evidence": evidence,
                    "price": _num(vals.get("price")), "breakout_price": _num(vals.get("breakout")),
                    "projected_ratio": _num(vals.get("projected_ratio")),
                    "live_volume_ratio": _num(vals.get("live_volume_ratio")),
                    "volume_delta_lots": _num(vals.get("volume_delta_lots")),
                    "window_s": _num(vals.get("window_s")),
                    "trigger_age_s": _num(vals.get("trigger_age_s")),
                    "snapshot_received_age_s": _num(vals.get("snapshot_received_age_s")),
                    "source_line": lineno,
                }
                seed = f"{pred['timestamp']}:{symbol}:{level}:{evidence}:{pred['price']}:{pred['breakout_price']}:{pred['projected_ratio']}"
                pred["signal_id"] = hashlib.sha256(seed.encode()).hexdigest()[:24]
                predictions.append(pred); events.append(pred)

            m = CANDIDATE.search(content)
            if m:
                candidate = {"timestamp": at, "symbol": m.group(1), "name": m.group(2).strip(), "change_pct": _num(m.group(3)), "breakout_price": _num(m.group(4)), "vma5_lots": _num(m.group(5)), "source_line": lineno}
                candidates.append(candidate); events.append({"event_type": "dynamic_candidate", **candidate})

            if "TELEGRAM SEND TIMING" in content or "TELEGRAM DELIVERY" in content:
                vals = _extract_values(content)
                sym = re.search(r"(?:TELEGRAM SEND TIMING|TELEGRAM DELIVERY)\s*\|\s*(\d{4})", content)
                status = (vals.get("status") or "UNKNOWN").upper()
                notify = {"timestamp": at, "symbol": sym.group(1) if sym else None, "evidence": vals.get("evidence"), "status": status, "source_line": lineno}
                notifications.append(notify); events.append({"event_type": "notification", **notify})

            if "MIS FETCH TIMING" in content:
                vals = _extract_values(content)
                row = {"timestamp": at, "source_line": lineno}
                for key in ("requested", "returned", "raw_items", "missing_z", "invalid_y", "missing_symbol", "quote_time_unknown", "failed_batches", "wall_ms", "provider_ms", "batches"):
                    row[key] = _num(vals.get(key))
                if row.get("requested") is not None and row.get("returned") is not None:
                    row["coverage_pct"] = round(100 * row["returned"] / max(1, row["requested"]), 2)
                    fetch_metrics.append(row)

            m = re.search(r"RADAR INTERVAL\s*\|[^\n]*?start_to_start_s=([\d.]+)", content)
            if m: intervals.append(float(m.group(1)))

            if "PHASE ->" in content:
                p = re.search(r"PHASE ->\s*([A-Z_]+)\s*\|\s*(\d\d:\d\d:\d\d)", content)
                if p:
                    phases.append({"phase": p.group(1), "time_taipei": p.group(2), "timestamp": at, "source_line": lineno})

            # Parse rendered watchlist rows but never claim they are tick-level or fresh quotes.
            wm = WATCH_ROW.match(content)
            if wm:
                q = wm.groupdict()
                price = None if q["price"] == "--" else _num(q["price"])
                quote = {"timestamp": at, "symbol": q["symbol"], "name": q["name"].strip(), "bucket": q["bucket"], "market": q["market"], "display_price": price, "flag": bool(q["flag"]), "status": q["status"], "source_line": lineno, "freshness_verified": False}
                quotes.append(quote)

            if "GROUND_TRUTH ERROR" in content or "GROUND_TRUTH CUTOFF ERROR" in content:
                err = {"timestamp": at, "message": content[:300], "source_line": lineno, "error_type": "ground_truth_error"}
                errors.append(err)
            elif re.search(r"\b(ERROR|FATAL ERROR|EXCEPTION)\b", content, re.I) and any(x in content for x in ("RADAR", "PERSISTENCE", "FUGLE", "EXECUTION", "TRADE", "ORDER", "SUPABASE")):
                errors.append({"timestamp": at, "message": content[:300], "source_line": lineno, "error_type": "runtime_error"})
            if "HISTORY_MISSING_AFTER_BACKFILL" in content or "HISTORY_VALID_BARS_INSUFFICIENT" in content:
                # Production has two known formats: INIT_SYMBOL_FAILED symbol=3718 ...
                # and DYNAMIC HISTORY | 3535 | ... . Preserve the symbol so the
                # acceptance report does not undercount affected names.
                symbol_match = re.search(r"\bsymbol=(\d{4})\b", content)
                if not symbol_match:
                    symbol_match = re.search(r"DYNAMIC HISTORY\s*\|\s*(\d{4})\b", content)
                warnings.append({"timestamp": at, "symbol": symbol_match.group(1) if symbol_match else None,
                                 "message": content[:300], "source_line": lineno,
                                 "warning_type": "history_data_incomplete"})

        # Deduce run date from first timestamps, not the system clock.
        dated = [x["timestamp"] for x in radar_cycles if x.get("timestamp")]
        trade_date = dated[0][:10] if dated else None
        # Last rendered quote per symbol strictly before the 13:30 close; its freshness is unknown.
        close_cutoff = time(13, 30, 0)
        close_quotes: dict[str, dict[str, Any]] = {}
        for q in quotes:
            if q["display_price"] is None or not q["timestamp"]:
                continue
            dt = datetime.fromisoformat(q["timestamp"])
            if dt.timetz().replace(tzinfo=None) <= close_cutoff:
                prior = close_quotes.get(q["symbol"])
                if prior is None or q["timestamp"] > prior["timestamp"]:
                    close_quotes[q["symbol"]] = q

        # Fill any stock names only from rows and signal logs in the source itself.
        names = {}
        for q in quotes: names[q["symbol"]] = q["name"]
        for t in triggers: names[t["symbol"]] = t["name"]
        for c in candidates: names[c["symbol"]] = c["name"]

        stage_summary = {
            "stage0_pass_complete": stage.get("stage0_pass_complete"),
            "stage0_pass_input_to_stage1": stage.get("stage0_pass_input_to_stage1"),
            "stage1_pass": stage.get("stage1_pass"),
            "stage1_pass_input_to_stage2": stage.get("stage1_pass_input_to_stage2"),
            "stage2_pass_input_to_stage3": stage.get("stage2_pass_input_to_stage3"),
            "stage2_pass": stage.get("stage2_pass"),
            "stage2_fail_unknown": stage.get("stage2_fail_unknown"),
            "stage3_pass": stage.get("stage3_pass"),
            "stage3_fail_unknown": stage.get("stage3_fail_unknown"),
            "premarket_3k_pass": stage.get("premarket_3k_pass"),
            "premarket_pool": stage.get("premarket_pool", []),
        }
        trades, decisions, sim_summary = self._simulate(predictions, close_quotes, names, trade_date)

        levels = Counter(p["level"] for p in predictions)
        evidences = Counter(p["evidence"] for p in predictions)
        trigger_symbols = sorted({x["symbol"] for x in triggers})
        cand_symbols = sorted({x["symbol"] for x in candidates})
        gterr = [e for e in errors if e["error_type"] == "ground_truth_error"]
        gt_cutoff = None
        for line in lines:
            m = re.search(r"GROUND_TRUTH CUTOFF VALIDATION\s*\|\s*predictions=(\d+)\s*\|\s*unavailable=(\d+)", line)
            if m:
                gt_cutoff = {"predictions": int(m.group(1)), "unavailable": int(m.group(2)), "available": int(m.group(1))-int(m.group(2))}
        avg_coverage = round(sum(x["coverage_pct"] for x in fetch_metrics) / len(fetch_metrics), 2) if fetch_metrics else None
        latest_cycle = radar_cycles[-1] if radar_cycles else None
        cycle_interval_sorted = sorted(intervals)
        p95_interval = cycle_interval_sorted[min(len(cycle_interval_sorted)-1, int(0.95*len(cycle_interval_sorted)))] if cycle_interval_sorted else None

        report = {
            "schema_version": 1,
            "report_type": "tianji_intraday_log_replay",
            "mode": "OFFLINE_PAPER_REPLAY_ONLY",
            "source": {"file": Path(source).name, "zip_member": member, "sha256": source_hash, "line_count": len(lines), "trade_date": trade_date},
            "config": asdict(self.config),
            "pipeline": {
                "premarket": {**stage_summary, "passed_count_matches_final_pool": len(stage_summary["premarket_pool"]) == (stage_summary["premarket_3k_pass"] or 0), "stage0_to_stage1_count_gap": (stage_summary["stage0_pass_complete"] - stage_summary["stage0_pass_input_to_stage1"]) if stage_summary.get("stage0_pass_complete") is not None and stage_summary.get("stage0_pass_input_to_stage1") is not None else None},
                "intraday": {"radar_cycles": len(radar_cycles), "first_cycle": radar_cycles[0] if radar_cycles else None, "last_cycle": latest_cycle, "max_monitoring_symbols": max((x["monitoring_symbols"] for x in radar_cycles), default=0), "max_mis_returned_symbols": max((x["mis_returned_symbols"] for x in radar_cycles), default=0), "unique_dynamic_candidate_symbols": len(cand_symbols), "dynamic_candidate_events": len(candidates), "breakout_trigger_events": len(triggers), "unique_trigger_symbols": len(trigger_symbols), "prediction_events": len(predictions), "prediction_levels": dict(levels), "prediction_evidence": dict(evidences), "explicit_telegram_send_events": len(notifications), "explicit_telegram_sent": sum(1 for n in notifications if n["status"] == "SENT"), "mis_fetch_samples": len(fetch_metrics), "average_mis_quote_coverage_pct": avg_coverage, "min_mis_quote_coverage_pct": min((x["coverage_pct"] for x in fetch_metrics), default=None), "max_mis_quote_coverage_pct": max((x["coverage_pct"] for x in fetch_metrics), default=None), "radar_start_interval_count": len(intervals), "radar_interval_average_seconds": round(sum(intervals)/len(intervals), 2) if intervals else None, "radar_interval_p95_seconds": p95_interval, "radar_interval_max_seconds": max(intervals) if intervals else None, "radar_intervals_over_22s": sum(1 for x in intervals if x > 22.0)},
                "close": {"last_phase": phases[-1] if phases else None, "ground_truth_error_count": len(gterr), "ground_truth_cutoff": gt_cutoff, "verification_status": "FAILED" if gterr or (gt_cutoff and gt_cutoff["unavailable"] > 0) else ("NOT_RECORDED" if not gt_cutoff else "PASS"), "key_errors": gterr[:8]},
            },
            "simulation": sim_summary,
            "trade_rows": trades,
            "entry_decisions": decisions,
            "data_quality": {
                "watchlist_display_rows": len(quotes),
                "priced_display_rows": sum(1 for q in quotes if q["display_price"] is not None),
                "display_quote_freshness_proven": False,
                "execution_price_path_available": False,
                "ground_truth_available": bool(gt_cutoff and gt_cutoff["available"] > 0),
                "limitations": [
                    "GitHub Actions LOG 是執行紀錄，不是完整 tick/1m/5m OHLCV 歷史行情。",
                    "監控表格的價格行無法證明報價時間與新鮮度；只能作為收盤代理價情境，不能當官方收盤價。",
                    "沒有部分成交、委託回報或券商交易紀錄；訂單／成交是本次模擬，不是實際成交。",
                    "Ground Truth cutoff 顯示當日所有預測不可驗證，因此不能把模擬損益當成策略績效或命中率。",
                ],
            },
            "runtime_warnings": {"history_data_incomplete_count": len(warnings),
                                 "history_data_incomplete_unique_symbols": sorted({x["symbol"] for x in warnings if x.get("symbol")}),
                                 "history_data_incomplete_unidentified_count": sum(1 for x in warnings if not x.get("symbol"))},
            "acceptance_matrix": {
                "premarket_scan_reconstruction": "PASS_WITH_COUNT_GAP" if stage_summary.get("stage0_pass_complete") != stage_summary.get("stage0_pass_input_to_stage1") else "PASS",
                "intraday_radar_log_replay": "PASS_WITH_LOW_MIS_COVERAGE" if avg_coverage is not None and avg_coverage < 50 else "PASS",
                "paper_order_decision_replay": "PASS_SIMULATED_ONLY",
                "supabase_durable_write_and_restart_recovery": "NOT_VERIFIABLE_FROM_THIS_LOG",
                "intraday_stop_take_path": "NOT_VERIFIABLE_NO_FRESH_FULL_PRICE_PATH",
                "close_ground_truth": "FAIL" if gterr or (gt_cutoff and gt_cutoff["unavailable"] > 0) else ("NOT_RECORDED" if not gt_cutoff else "PASS"),
                "live_trading_readiness": "NO_GO",
            },
            "audit_events": events,
        }
        return report

    def _simulate(self, predictions: list[dict[str, Any]], close_quotes: dict[str, dict[str, Any]], names: dict[str, str], trade_date: str | None):
        cfg = self.config
        cash = Decimal(cfg.starting_cash)
        initial_cash = cash
        commission = Decimal(cfg.commission_rate)
        sell_tax = Decimal(cfg.sell_tax_rate)
        slip_bps = Decimal(cfg.slippage_bps)
        slip_rate = slip_bps / Decimal("10000")
        min_ratio = Decimal(cfg.min_projected_volume_ratio)
        stop_pct = Decimal(cfg.stop_loss_pct)
        target_pct = Decimal(cfg.take_profit_pct)
        cutoff = time.fromisoformat(cfg.entry_cutoff_taipei)
        policy = EntryPolicy(
            min_projected_ratio=min_ratio,
            max_trigger_age_seconds=cfg.max_trigger_age_seconds,
            max_snapshot_age_seconds=cfg.max_snapshot_received_age_seconds,
            max_order_notional=Decimal(cfg.max_order_notional),
            commission_rate=commission,
            max_positions=cfg.max_positions,
            entry_cutoff=cutoff,
        )
        positions: dict[str, dict[str, Any]] = {}
        trades: list[dict[str, Any]] = []
        decisions: list[dict[str, Any]] = []
        traded_symbols: set[str] = set()
        seen_ids: set[str] = set()

        for p in sorted(predictions, key=lambda x: (x.get("timestamp") or "", x["source_line"])):
            symbol = p["symbol"]
            if p["signal_id"] in seen_ids:
                decisions.append({"signal_id": p["signal_id"], "symbol": symbol, "timestamp": p.get("timestamp"), "decision": "NO_ORDER", "reason": "DUPLICATE_SIGNAL_ID", "source_line": p["source_line"]})
                continue
            seen_ids.add(p["signal_id"])
            # The isolated replay ledger is deterministic and in-memory. This flag only
            # says the local simulator is operational; it is not a claim of Supabase readiness.
            context = EntryContext(
                persistence_ready=True,
                market_data_ready=True,
                cash=cash,
                open_symbols=frozenset(positions.keys()),
                traded_symbols_today=frozenset(traded_symbols),
                open_position_count=len(positions),
                daily_loss_pct=Decimal("0"),
            )
            allowed, reason = evaluate_entry(p, context, policy)
            if not allowed:
                decisions.append({"signal_id": p["signal_id"], "symbol": symbol, "timestamp": p.get("timestamp"), "decision": "NO_ORDER", "reason": reason, "source_line": p["source_line"]})
                continue

            reference = Decimal(str(p["price"]))
            sizing = size_position(reference, cash, policy, slip_bps)
            qty = int(sizing["quantity"])
            if qty <= 0:
                decisions.append({"signal_id": p["signal_id"], "symbol": symbol, "timestamp": p.get("timestamp"), "decision": "NO_ORDER", "reason": "INSUFFICIENT_PAPER_CASH_OR_LOT", "source_line": p["source_line"]})
                continue
            fill_price = Decimal(str(sizing["fill_price"]))
            notional = Decimal(str(sizing["notional"]))
            buy_fee = Decimal(str(sizing["fee"]))
            total_cost = Decimal(str(sizing["total_cost"]))
            cash -= total_cost
            order_id = hashlib.sha256(f"{p['signal_id']}:paper-order".encode()).hexdigest()[:24]
            positions[symbol] = {
                "symbol": symbol, "name": names.get(symbol) or symbol, "signal_id": p["signal_id"], "order_id": order_id,
                "entry_timestamp": p.get("timestamp"), "signal_price": str(reference), "entry_fill_price": str(fill_price),
                "quantity": qty, "entry_notional": str(notional), "entry_fee": str(buy_fee),
                "projected_ratio": p["projected_ratio"], "breakout_price": p["breakout_price"],
                "entry_evidence": p["evidence"], "entry_level": p["level"], "entry_source_line": p["source_line"],
                "stop_loss_trigger_price": str((fill_price * (Decimal("1") - stop_pct)).quantize(Decimal("0.0001"))),
                "take_profit_trigger_price": str((fill_price * (Decimal("1") + target_pct)).quantize(Decimal("0.0001"))),
                "exit_check_status": "NOT_EVALUATED_NO_COMPLETE_FRESH_PRICE_PATH",
                "exit_policy": {"stop_loss_pct": str(stop_pct), "take_profit_pct": str(target_pct),
                                "intraday_exit_check": "NOT_RUN_FROM_LOG: quote freshness and full price path unavailable"},
            }
            traded_symbols.add(symbol)
            decisions.append({"signal_id": p["signal_id"], "symbol": symbol, "timestamp": p.get("timestamp"),
                              "decision": "PAPER_ORDER_FILLED_ASSUMED", "reason": reason, "order_id": order_id,
                              "quantity": qty, "reference_price": str(reference), "assumed_fill_price": str(fill_price),
                              "source_line": p["source_line"]})

        # Strictly use the last non-empty rendered quote before 13:30 as an unverified
        # close proxy. Never infer intraday stop/target touches from potentially cached rows.
        for symbol, pos in list(positions.items()):
            q = close_quotes.get(symbol)
            if not q or q.get("display_price") is None or not q.get("timestamp") or q["timestamp"] <= (pos.get("entry_timestamp") or ""):
                pos.update({"exit_status": "UNRESOLVED_NO_POST_ENTRY_MARK", "mark_price": None, "net_pnl": None})
                trades.append(pos)
                continue
            ref_exit = Decimal(str(q["display_price"]))
            exit_fill = ref_exit * (Decimal("1") - slip_rate)  # adverse SELL slippage assumption
            notional = exit_fill * int(pos["quantity"])
            exit_fee = notional * commission
            tax = notional * sell_tax
            proceeds = notional - exit_fee - tax
            buy_cost = Decimal(pos["entry_notional"]) + Decimal(pos["entry_fee"])
            pnl = proceeds - buy_cost
            cash += proceeds
            pnl_pct = (pnl / buy_cost * Decimal("100")) if buy_cost else Decimal("0")
            pos.update({"exit_timestamp": q["timestamp"], "mark_price": str(ref_exit), "exit_fill_price": str(exit_fill),
                        "exit_status": "CLOSED_AT_LAST_DISPLAY_MARK_PROXY", "exit_reason": "LAST_NONEMPTY_DISPLAY_PRICE_NOT_VERIFIED_CLOSE",
                        "exit_source_line": q["source_line"], "exit_source": "watchlist rendered price; timestamp is log write time; quote freshness unverified",
                        "exit_notional": str(notional), "exit_fee": str(exit_fee), "sell_tax_assumption": str(tax),
                        "net_pnl": str(pnl.quantize(Decimal('0.01'))), "net_return_pct": str(pnl_pct.quantize(Decimal('0.01'))),
                        "buy_cost_including_fee": str(buy_cost.quantize(Decimal('0.01')))})
            trades.append(pos)

        closed = [t for t in trades if t.get("net_pnl") is not None]
        net_pnl = sum((Decimal(t["net_pnl"]) for t in closed), Decimal("0"))
        gross_pnl = sum((Decimal(t["mark_price"]) * int(t["quantity"]) - Decimal(t["signal_price"]) * int(t["quantity"]) for t in closed), Decimal("0"))
        summary = {
            "status": "COMPLETED_WITH_UNVERIFIED_MARKS" if closed else "NO_QUALIFIED_TRADES",
            "entry_policy": "FUGLE_5M + STRONG + projected_ratio >= threshold + trigger/snapshot freshness + breakout valid + time/risk gate",
            "orders_assumed_filled": sum(1 for d in decisions if d["decision"] == "PAPER_ORDER_FILLED_ASSUMED"),
            "signals_not_ordered": sum(1 for d in decisions if d["decision"] == "NO_ORDER"),
            "open_positions_unresolved": sum(1 for t in trades if t.get("net_pnl") is None),
            "initial_cash": str(initial_cash), "cash_after_replay": str(cash.quantize(Decimal('0.01'))),
            "gross_pnl_before_costs": str(gross_pnl.quantize(Decimal('0.01'))),
            "net_pnl_after_assumed_costs": str(net_pnl.quantize(Decimal('0.01'))),
            "net_return_on_initial_cash_pct": str((net_pnl / initial_cash * Decimal('100')).quantize(Decimal('0.0001')) if initial_cash else Decimal('0')),
            "winning_trades_proxy": sum(1 for t in closed if Decimal(t["net_pnl"]) > 0),
            "losing_trades_proxy": sum(1 for t in closed if Decimal(t["net_pnl"]) < 0),
            "proxy_win_rate_pct": str((Decimal(sum(1 for t in closed if Decimal(t["net_pnl"]) > 0)) / Decimal(len(closed)) * Decimal('100')).quantize(Decimal('0.01')) if closed else None),
            "cost_assumptions": {"commission_rate_each_side": cfg.commission_rate, "sell_tax_rate": cfg.sell_tax_rate,
                                 "adverse_slippage_bps_each_side": cfg.slippage_bps, "max_order_notional": cfg.max_order_notional},
            "pnl_is_verified_strategy_performance": False,
            "exit_checks": "Stop-loss / take-profit were not triggered from this log because rendered watchlist rows cannot prove quote freshness and do not constitute a complete intraday price path; logic must be tested using synthetic/fresh quote scenarios.",
        }
        return trades, decisions, summary


def write_replay_outputs(report: dict[str, Any], out_dir: str | Path) -> dict[str, str]:
    out = Path(out_dir).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / "replay_report.json"
    md_path = out / "replay_report.md"
    csv_path = out / "paper_trades.csv"
    decisions_path = out / "entry_decisions.csv"
    events_path = out / "audit_events.jsonl"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
        rows = report.get("trade_rows", [])
        keys = sorted({k for row in rows for k in row})
        writer = csv.DictWriter(f, fieldnames=keys or ["symbol"], extrasaction="ignore")
        writer.writeheader(); writer.writerows(rows)
    with decisions_path.open("w", newline="", encoding="utf-8-sig") as f:
        rows = report.get("entry_decisions", [])
        keys = sorted({k for row in rows for k in row})
        writer = csv.DictWriter(f, fieldnames=keys or ["symbol"], extrasaction="ignore")
        writer.writeheader(); writer.writerows(rows)
    with events_path.open("w", encoding="utf-8") as f:
        for event in report.get("audit_events", []): f.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
    pipe = report.get("pipeline", {}); pre = pipe.get("premarket", {}); intra = pipe.get("intraday", {}); close = pipe.get("close", {}); sim = report.get("simulation", {}); dq = report.get("data_quality", {})
    trade_lines = ["| 股票 | 進場時間 | 模擬進場價 | 股數 | 收盤代理價 | 淨損益（代理） | 狀態 |", "|---|---:|---:|---:|---:|---:|---|"]
    for t in report.get("trade_rows", []):
        trade_lines.append(f"| {t.get('symbol')} {t.get('name','')} | {t.get('entry_timestamp','')} | {t.get('entry_fill_price','')} | {t.get('quantity','')} | {t.get('mark_price') or 'N/A'} | {t.get('net_pnl') or '未能估算'} | {t.get('exit_status','')} |")
    md = f"""# 天機 3K 離線盤中交易重播報告

- 模式：`{report.get('mode')}`
- 日期：`{report.get('source',{}).get('trade_date')}`
- 原始檔 SHA-256：`{report.get('source',{}).get('sha256')}`
- 來源行數：{report.get('source',{}).get('line_count')}

## 流程重建

| 階段 | LOG 可見結果 |
|---|---|
| Stage 0 完整驗證通過 | {pre.get('stage0_pass_complete')} |
| Stage 0 傳入 Stage 1 | {pre.get('stage0_pass_input_to_stage1')} |
| Stage 1 趨勢通過 | {pre.get('stage1_pass')} |
| Stage 1 傳入 Stage 2 | {pre.get('stage1_pass_input_to_stage2')} |
| Stage 2 突破通過 / 未通過 | {pre.get('stage2_pass')} / {pre.get('stage2_fail_unknown')} |
| Stage 2 傳入 Stage 3 | {pre.get('stage2_pass_input_to_stage3')} |
| Stage 3 量能通過 / 未通過 | {pre.get('stage3_pass')} / {pre.get('stage3_fail_unknown')} |
| 最終 3K PASS | {pre.get('premarket_3k_pass')} |
| 盤中 Radar cycle | {intra.get('radar_cycles')} |
| 動態候選事件 / 不重複股票 | {intra.get('dynamic_candidate_events')} / {intra.get('unique_dynamic_candidate_symbols')} |
| 突破觸發事件 / 不重複股票 | {intra.get('breakout_trigger_events')} / {intra.get('unique_trigger_symbols')} |
| 預測事件 | {intra.get('prediction_events')} |
| LOG 明確記載 Telegram SENT | {intra.get('explicit_telegram_sent')} / 明確送出紀錄 {intra.get('explicit_telegram_send_events')} |
| MIS 回傳覆蓋率平均 / 最低 / 最高 | {intra.get('average_mis_quote_coverage_pct')}% / {intra.get('min_mis_quote_coverage_pct')}% / {intra.get('max_mis_quote_coverage_pct')}%（有效報價數 / requested） |
| Radar 週期平均 / P95 / 最長 | {intra.get('radar_interval_average_seconds')} 秒 / {intra.get('radar_interval_p95_seconds')} 秒 / {intra.get('radar_interval_max_seconds')} 秒 |

## 嚴格模擬交易結果

- 下單策略：{sim.get('entry_policy')}
- 模擬假定成交：{sim.get('orders_assumed_filled')}
- 未下單訊號：{sim.get('signals_not_ordered')}
- 代理收盤淨損益：{sim.get('net_pnl_after_assumed_costs')}
- 代理報酬率：{sim.get('net_return_on_initial_cash_pct')}%
- **以上損益不是已驗證策略績效。出場價是最後一筆非空監控表格顯示值，不是可確認的官方收盤價；報價新鮮度未能從 LOG 證明。**

{chr(10).join(trade_lines)}

## 三道驗收矩陣

| 驗收項目 | 狀態 |
|---|---|
| 盤前掃描重建 | {report.get('acceptance_matrix',{}).get('premarket_scan_reconstruction')} |
| 盤中 Radar 重播 | {report.get('acceptance_matrix',{}).get('intraday_radar_log_replay')} |
| 紙上交易決策重播 | {report.get('acceptance_matrix',{}).get('paper_order_decision_replay')} |
| Supabase 持久化／重啟恢復 | {report.get('acceptance_matrix',{}).get('supabase_durable_write_and_restart_recovery')} |
| 盤中停損／停利路徑 | {report.get('acceptance_matrix',{}).get('intraday_stop_take_path')} |
| 真實交易準備度 | **{report.get('acceptance_matrix',{}).get('live_trading_readiness')}** |

> Fault-gate / order-lifecycle unit tests cover persistence-not-ready, stale quotes, daily duplicate prevention, position limits, partial-fill state, UNKNOWN-order handling, and fresh-quote stop/target decisions. They are software-level tests, not a real Supabase outage/restart or broker-fill integration test.

## 收盤驗收

- Ground Truth 狀態：**{close.get('verification_status')}**
- cutoff 摘要：`{json.dumps(close.get('ground_truth_cutoff'), ensure_ascii=False)}`
- Ground Truth 錯誤次數：{close.get('ground_truth_error_count')}
- 盤中歷史資料不完整警告：{report.get('runtime_warnings',{}).get('history_data_incomplete_count')}
- 涉及不重複股票：{', '.join(report.get('runtime_warnings',{}).get('history_data_incomplete_unique_symbols', [])) or '無法由 LOG 識別'}
- 無法識別股票代碼的警告筆數：{report.get('runtime_warnings',{}).get('history_data_incomplete_unidentified_count')}

## 重要限制

""" + "\n".join(f"- {x}" for x in dq.get("limitations", [])) + "\n"
    md_path.write_text(md, encoding="utf-8")
    return {"report_json": str(json_path), "report_markdown": str(md_path), "paper_trades_csv": str(csv_path), "entry_decisions_csv": str(decisions_path), "audit_events_jsonl": str(events_path)}
