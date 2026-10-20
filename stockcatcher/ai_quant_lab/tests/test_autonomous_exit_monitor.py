import sys, unittest
from pathlib import Path
from decimal import Decimal
from types import SimpleNamespace
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))
from autonomy import AutonomousLoop

class FakeStore:
    configured = True

class FakeEngine:
    def __init__(self, qty=10, avg="100"):
        self.store = FakeStore()
        self.ledger = SimpleNamespace(positions={"2330": SimpleNamespace(quantity=qty, average_price=Decimal(avg))})
        self.events = []
    def process(self, event):
        self.events.append(event)
        p = event["payload"]; px = Decimal(p["mark_price"]); avg = self.ledger.positions["2330"].average_price
        if px <= avg * Decimal("0.98"): reason = "STOP_LOSS"
        elif px >= avg * Decimal("1.04"): reason = "TAKE_PROFIT"
        else: return {"status":"processed","actions":["exit_not_triggered"]}
        pos = self.ledger.positions.pop("2330")
        return {"status":"processed","exit_reason":reason,"fill":{"symbol":"2330","side":"SELL","quantity":pos.quantity,"price":str(px)}}

class FakeRadar:
    def __init__(self, quote): self.snapshot={"2330":quote}

def quote(price, stale=False):
    return {"symbol":"2330","name":"台積電","price":price,"current_price":price,"stale":stale,
            "is_traded":True,"data_age_seconds":1,"data_identity":f"q-{price}","source":"fake MIS"}

class AutomaticExitMonitorTests(unittest.TestCase):
    def loop(self, price, stale=False, configured=True):
        engine=FakeEngine(); engine.store.configured=configured
        loop=AutonomousLoop(engine, client=object(), watchlist=[], interval=20); loop.radar=FakeRadar(quote(price, stale))
        return loop, engine
    def test_fresh_quote_triggers_stop_loss_automatically(self):
        loop, engine=self.loop(97); results=[]; loop._monitor_open_positions(results, "2026-10-18T10:00:00+08:00")
        self.assertEqual(results[0]["status"], "paper_stop_loss"); self.assertEqual(engine.events[0]["event_type"], "paper.exit_check")
        self.assertEqual(engine.events[0]["payload"]["mode"], "paper")
    def test_fresh_quote_triggers_take_profit_automatically(self):
        loop, engine=self.loop(105); results=[]; loop._monitor_open_positions(results, "2026-10-18T10:00:00+08:00")
        self.assertEqual(results[0]["status"], "paper_take_profit"); self.assertEqual(results[0]["reason"], "TAKE_PROFIT")
    def test_non_triggering_quote_keeps_monitoring(self):
        loop, engine=self.loop(101); results=[]; loop._monitor_open_positions(results, "2026-10-18T10:00:00+08:00")
        self.assertEqual(results, []); self.assertEqual(len(engine.events), 1)
    def test_stale_quote_never_triggers_exit(self):
        loop, engine=self.loop(90, stale=True); results=[]; loop._monitor_open_positions(results, "2026-10-18T10:00:00+08:00")
        self.assertEqual(results, []); self.assertEqual(engine.events, [])
    def test_unconfigured_persistence_blocks_automatic_exit(self):
        loop, engine=self.loop(90, configured=False); results=[]; loop._monitor_open_positions(results, "2026-10-18T10:00:00+08:00")
        self.assertEqual(results, []); self.assertEqual(engine.events, [])

if __name__ == "__main__": unittest.main()
