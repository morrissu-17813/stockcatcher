import sys
import unittest
from decimal import Decimal
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from paper_trading.ledger import PaperLedger

class PaperLedgerTests(unittest.TestCase):
    def test_buy_then_sell_calculates_pnl_and_fees(self):
        ledger = PaperLedger(Decimal("100000"), Decimal("0.001"))
        ledger.execute("2330", "BUY", 10, Decimal("100"))
        fill = ledger.execute("2330", "SELL", 5, Decimal("120"))
        self.assertEqual(ledger.positions["2330"].quantity, 5)
        self.assertGreater(fill.realized_pnl, Decimal("0"))
        snap = ledger.snapshot({"2330": Decimal("120")})
        self.assertEqual(snap["positions"][0]["quantity"], 5)
        self.assertGreater(Decimal(snap["total_pnl"]), Decimal("0"))

    def test_buy_commission_is_included_in_cost_basis(self):
        ledger = PaperLedger(Decimal("100000"), Decimal("0.001"))
        buy = ledger.execute("2330", "BUY", 10, Decimal("100"))
        self.assertEqual(buy.fee, Decimal("1.00"))
        self.assertEqual(ledger.positions["2330"].average_price, Decimal("100.1"))
        sell = ledger.execute("2330", "SELL", 10, Decimal("100"))
        self.assertEqual(sell.realized_pnl, Decimal("-2.00"))
        snap = ledger.snapshot()
        self.assertEqual(Decimal(snap["total_pnl"]), Decimal("-2.00"))
        self.assertEqual(Decimal(snap["realized_pnl"]), Decimal("-2.00"))

    def test_replay_can_use_historical_fee_override(self):
        ledger = PaperLedger(Decimal("100000"), Decimal("0.01"))
        fill = ledger.execute("2330", "BUY", 10, Decimal("100"), fee_override=Decimal("0.25"))
        self.assertEqual(fill.fee, Decimal("0.25"))
        self.assertEqual(ledger.positions["2330"].average_price, Decimal("100.025"))

    def test_rejects_negative_fee_override(self):
        ledger = PaperLedger()
        with self.assertRaisesRegex(ValueError, "fee cannot be negative"):
            ledger.execute("2330", "BUY", 1, Decimal("100"), fee_override=Decimal("-0.01"))

    def test_rejects_insufficient_cash(self):
        ledger = PaperLedger(Decimal("1000"))
        with self.assertRaisesRegex(ValueError, "insufficient"):
            ledger.execute("2330", "BUY", 10, Decimal("1000"))

    def test_rejects_short_sell(self):
        ledger = PaperLedger()
        with self.assertRaisesRegex(ValueError, "cannot sell"):
            ledger.execute("2330", "SELL", 1, Decimal("100"))

    def test_rejects_invalid_quantity(self):
        ledger = PaperLedger()
        with self.assertRaises(ValueError):
            ledger.execute("2330", "BUY", 0, Decimal("100"))

if __name__ == "__main__":
    unittest.main()
