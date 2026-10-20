from __future__ import annotations
import sys
import tempfile
import unittest
import zipfile
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from log_replay import TianjiLogReplay, ReplayConfig, write_replay_outputs
from intraday_execution import EntryContext, EntryPolicy, evaluate_entry, evaluate_exit, size_position

FIXTURE = ROOT / "tests" / "fixtures" / "tianji_log_replay_sample.txt"


class LogReplayTests(unittest.TestCase):
    def test_stage_and_signal_pipeline_are_reconstructed(self):
        report = TianjiLogReplay().run(FIXTURE)
        pre = report["pipeline"]["premarket"]
        intra = report["pipeline"]["intraday"]
        self.assertEqual(pre["stage0_pass_complete"], 345)
        self.assertEqual(pre["stage0_pass_input_to_stage1"], 344)
        self.assertEqual(pre["stage1_pass"], 145)
        self.assertEqual(pre["stage2_pass"], 2)
        self.assertEqual(pre["stage2_fail_unknown"], 143)
        self.assertEqual(pre["stage3_pass"], 2)
        self.assertEqual([x["symbol"] for x in pre["premarket_pool"]], ["4904", "6278"])
        self.assertEqual(intra["radar_cycles"], 1)
        self.assertEqual(intra["breakout_trigger_events"], 1)
        self.assertEqual(intra["prediction_events"], 3)

    def test_strict_policy_only_simulates_strong_fugle_entry(self):
        report = TianjiLogReplay().run(FIXTURE)
        self.assertEqual(report["simulation"]["orders_assumed_filled"], 1)
        self.assertEqual(report["simulation"]["signals_not_ordered"], 2)
        self.assertEqual(report["trade_rows"][0]["symbol"], "3167")
        self.assertFalse(report["simulation"]["pnl_is_verified_strategy_performance"])

    def test_close_ground_truth_failure_is_never_hidden(self):
        report = TianjiLogReplay().run(FIXTURE)
        self.assertEqual(report["pipeline"]["close"]["verification_status"], "FAILED")
        self.assertEqual(report["pipeline"]["close"]["ground_truth_cutoff"]["unavailable"], 3)
        self.assertEqual(report["acceptance_matrix"]["live_trading_readiness"], "NO_GO")

    def test_watchlist_close_mark_is_explicitly_unverified(self):
        report = TianjiLogReplay().run(FIXTURE)
        trade = report["trade_rows"][0]
        self.assertEqual(trade["mark_price"], "101.0")
        self.assertEqual(trade["exit_status"], "CLOSED_AT_LAST_DISPLAY_MARK_PROXY")
        self.assertIn("freshness unverified", trade["exit_source"])

    def test_reads_zip_without_extracting_paths(self):
        with tempfile.TemporaryDirectory() as td:
            zip_path = Path(td) / "sample.zip"
            with zipfile.ZipFile(zip_path, "w") as zf:
                zf.write(FIXTURE, "nested/run.txt")
                zf.writestr("system.txt", "not the operational log")
            report = TianjiLogReplay().run(zip_path)
            self.assertEqual(report["source"]["zip_member"], "nested/run.txt")
            self.assertEqual(report["pipeline"]["intraday"]["prediction_events"], 3)


    def test_same_signal_repeat_is_idempotently_rejected_in_replay(self):
        # Two identical source events at the same timestamp must share a stable ID.
        text = FIXTURE.read_text(encoding="utf-8")
        target = next(line for line in text.splitlines() if "3167 | level=STRONG" in line)
        repeated = text + "\n" + target + "\n"
        with tempfile.TemporaryDirectory() as td:
            log_path = Path(td) / "duplicate.log"
            log_path.write_text(repeated, encoding="utf-8")
            report = TianjiLogReplay().run(log_path)
        reasons = [d["reason"] for d in report["entry_decisions"]]
        self.assertIn("DUPLICATE_SIGNAL_ID", reasons)
        self.assertEqual(report["simulation"]["orders_assumed_filled"], 1)

    def test_history_warnings_extract_both_production_log_formats(self):
        text = FIXTURE.read_text(encoding="utf-8")
        text += "\n2026-10-16T01:18:03.6421561Z ⚠️ DYNAMIC HISTORY | 3535 | RuntimeError: HISTORY_MISSING_AFTER_BACKFILL:2026-10-08 | attempt=1/3 | retry_after_s=60\n"
        text += "2026-10-16T01:18:04.6421561Z 2026-10-16 01:18:04,642 | WARNING | INIT_SYMBOL_FAILED symbol=3718 attempt=1/3 error=RuntimeError: HISTORY_VALID_BARS_INSUFFICIENT:28<61\n"
        with tempfile.TemporaryDirectory() as td:
            log_path = Path(td) / "history.log"
            log_path.write_text(text, encoding="utf-8")
            report = TianjiLogReplay().run(log_path)
        warnings = report["runtime_warnings"]
        self.assertEqual(warnings["history_data_incomplete_count"], 2)
        self.assertEqual(warnings["history_data_incomplete_unique_symbols"], ["3535", "3718"])
        self.assertEqual(warnings["history_data_incomplete_unidentified_count"], 0)

    def test_outputs_are_complete_and_machine_readable(self):
        with tempfile.TemporaryDirectory() as td:
            report = TianjiLogReplay().run(FIXTURE)
            outputs = write_replay_outputs(report, td)
            for path in outputs.values(): self.assertTrue(Path(path).exists())
            self.assertIn("收盤驗收", Path(outputs["report_markdown"]).read_text(encoding="utf-8"))


class EntryGateTests(unittest.TestCase):
    def valid_signal(self):
        return {"timestamp": "2026-10-16T11:51:00+08:00", "symbol": "3167", "level": "STRONG",
                "evidence": "FUGLE_5M", "price": 100, "breakout_price": 99, "projected_ratio": 2.7,
                "trigger_age_s": 20, "snapshot_received_age_s": 1}

    def context(self, **kwargs):
        base = dict(persistence_ready=True, market_data_ready=True, cash=Decimal("1000000"))
        base.update(kwargs)
        return EntryContext(**base)

    def test_persistence_failure_fails_closed(self):
        allowed, reason = evaluate_entry(self.valid_signal(), self.context(persistence_ready=False))
        self.assertFalse(allowed); self.assertEqual(reason, "PERSISTENCE_NOT_READY")

    def test_market_data_not_ready_fails_closed(self):
        allowed, reason = evaluate_entry(self.valid_signal(), self.context(market_data_ready=False))
        self.assertFalse(allowed); self.assertEqual(reason, "MARKET_DATA_NOT_READY")

    def test_early_and_mis_live_signals_are_blocked(self):
        signal = self.valid_signal(); signal["level"] = "EARLY"
        self.assertEqual(evaluate_entry(signal, self.context())[1], "REQUIRES_STRONG_LEVEL")
        signal = self.valid_signal(); signal["evidence"] = "MIS_LIVE"
        self.assertEqual(evaluate_entry(signal, self.context())[1], "REQUIRES_FUGLE_5M_CONFIRMATION")

    def test_stale_trigger_and_quote_are_blocked(self):
        signal = self.valid_signal(); signal["trigger_age_s"] = 301
        self.assertEqual(evaluate_entry(signal, self.context())[1], "TRIGGER_EXPIRED")
        signal = self.valid_signal(); signal["snapshot_received_age_s"] = 31
        self.assertEqual(evaluate_entry(signal, self.context())[1], "SNAPSHOT_STALE")

    def test_duplicate_daily_entry_position_cap_and_daily_loss_gate(self):
        signal = self.valid_signal()
        self.assertEqual(evaluate_entry(signal, self.context(open_symbols=frozenset({"3167"})))[1], "DUPLICATE_POSITION_OR_DAILY_REENTRY")
        self.assertEqual(evaluate_entry(signal, self.context(open_position_count=3))[1], "MAX_OPEN_POSITIONS")
        self.assertEqual(evaluate_entry(signal, self.context(daily_loss_pct=Decimal("0.02")))[1], "DAILY_LOSS_LIMIT")

    def test_outside_entry_window_is_blocked(self):
        signal = self.valid_signal(); signal["timestamp"] = "2026-10-16T13:25:00+08:00"
        self.assertEqual(evaluate_entry(signal, self.context())[1], "OUTSIDE_ENTRY_WINDOW")


    def test_exit_manager_uses_only_fresh_quotes(self):
        self.assertEqual(evaluate_exit(Decimal("100"), Decimal("97"), quote_age_seconds=1)[0], "STOP_LOSS")
        self.assertEqual(evaluate_exit(Decimal("100"), Decimal("104"), quote_age_seconds=1)[0], "TAKE_PROFIT")
        self.assertEqual(evaluate_exit(Decimal("100"), Decimal("97"), quote_age_seconds=45)[1], "EXIT_QUOTE_STALE")
        self.assertEqual(evaluate_exit(Decimal("100"), Decimal("104"), quote_age_seconds=None)[1], "EXIT_QUOTE_AGE_MISSING")

    def test_position_size_obeys_notional_and_available_cash(self):
        policy = EntryPolicy(max_order_notional=Decimal("100000"), commission_rate=Decimal("0.001425"))
        result = size_position(Decimal("1050"), Decimal("200000"), policy, Decimal("10"))
        self.assertGreater(result["quantity"], 0)
        self.assertLessEqual(result["notional"], Decimal("100000"))
        self.assertLessEqual(result["total_cost"], Decimal("200000"))
        self.assertEqual(size_position(Decimal("1050"), Decimal("100"), policy)["quantity"], 0)


if __name__ == "__main__":
    unittest.main()
