import sys, unittest
from pathlib import Path
from decimal import Decimal
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from engine import LabEngine
class RecoveryStore:
    configured=True
    def __init__(self,trades=None,events=None): self.trades=trades or []; self.events=events or []; self.trade_query=None
    def list_rows(self,table,**kwargs):
        if table=="ai_quant_lab_paper_trades":
            self.trade_query=kwargs; rows=sorted(self.trades,key=lambda r:(r.get("executed_at",""),r.get("created_at",""),r.get("trade_key","")))
        elif table=="ai_quant_lab_events": rows=sorted(self.events,key=lambda r:int(r.get("event_seq") or 0),reverse=True)
        else: return []
        off,lim=kwargs.get("offset",0),kwargs.get("limit",1000); return rows[off:off+lim]
def tr(k,side,q,price,ex,cr,fee="0.00"):
    return {"trade_key":k,"symbol":"2330","side":side,"quantity":q,"price":str(price),"fees":fee,"status":"FILLED","executed_at":ex,"created_at":cr}
class V27RecoveryTests(unittest.TestCase):
    def test_restart_restores_open_position_cash_and_summary(self):
        store=RecoveryStore([tr("buy-1","BUY",10,100,"2026-10-18T09:00:00+08:00","2026-10-18T09:00:00.001+08:00","1.00")],[{"event_key":"evt-1","event_seq":41,"event_type":"signal.created","occurred_at":"2026-10-18T09:00:00+08:00","payload":{"outcome":{"status":"processed"}}}])
        e=LabEngine(store=store,initial_cash=Decimal("1000000")); self.assertIsNone(e.restore_error); self.assertEqual(e.ledger.positions["2330"].quantity,10); self.assertEqual(e.ledger.cash,Decimal("998999.00")); self.assertEqual(e.recovery_summary["status"],"RESTORED"); self.assertEqual(e.recovery_summary["restored_open_positions"],1); self.assertEqual(e.recovery_summary["restored_fills"],1); self.assertEqual(e.recovery_summary["last_event_seq"],41); self.assertIn("created_at.asc",store.trade_query["order"])
    def test_same_timestamp_replays_in_created_order(self):
        store=RecoveryStore([tr("sell-2","SELL",5,110,"2026-10-18T09:00:00+08:00","2026-10-18T09:00:00.002+08:00","0.10"),tr("buy-1","BUY",10,100,"2026-10-18T09:00:00+08:00","2026-10-18T09:00:00.001+08:00","0.10")])
        e=LabEngine(store=store); self.assertIsNone(e.restore_error); self.assertEqual(e.ledger.positions["2330"].quantity,5); self.assertEqual([f.side for f in e.ledger.fills],["BUY","SELL"])
    def test_duplicate_trade_key_fails_closed(self):
        x=tr("same","BUY",1,100,"2026-10-18T09:00:00+08:00","2026-10-18T09:00:00.001+08:00"); e=LabEngine(store=RecoveryStore([x,dict(x)])); self.assertIsNotNone(e.restore_error); self.assertEqual(e.recovery_summary["status"],"FAILED"); self.assertIn("duplicate persisted paper trade key",e.restore_error)
    def test_missing_trade_fields_fails_closed(self):
        e=LabEngine(store=RecoveryStore([{"trade_key":"broken","status":"FILLED","symbol":"2330"}])); self.assertIsNotNone(e.restore_error); self.assertEqual(e.recovery_summary["status"],"FAILED")
    def test_restored_exit_event_is_idempotent(self):
        store=RecoveryStore(events=[{"event_key":"auto-exit-check:2330:q-97","event_seq":88,"event_type":"paper.exit_check","occurred_at":"2026-10-18T09:30:00+08:00","payload":{"event":{"payload":{"symbol":"2330"}},"outcome":{"status":"processed"}}}])
        e=LabEngine(store=store); r=e.process({"event_id":"auto-exit-check:2330:q-97","event_type":"paper.exit_check","occurred_at":"2026-10-18T09:30:00+08:00","source":"test","payload":{"mode":"paper","symbol":"2330","mark_price":"97","market_snapshot":{"data_age_seconds":1}}}); self.assertEqual(r["status"],"duplicate"); self.assertEqual(e.recovery_summary["restored_event_ids"],1)
if __name__=="__main__": unittest.main()
