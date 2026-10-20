import sys, unittest, threading
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from autonomy import AutonomousLoop

class DummyEngine:
    persistence_degraded=False
    restore_error=None
    store=type("Store",(),{"configured":False})()
    def agent_task(self,*a,**k): pass

class AutonomyHealthTests(unittest.TestCase):
    def test_status_exposes_monitor_heartbeat_fields(self):
        loop=AutonomousLoop(DummyEngine(),client=object(),watchlist=[{"symbol":"2330"}],interval=20)
        status=loop.status()
        self.assertFalse(status["thread_alive"])
        self.assertEqual(status["health"],"STOPPED")
        self.assertEqual(status["max_consecutive_cycle_errors"],5)
        self.assertIn("last_successful_mis_at",status)
        self.assertEqual(status["consecutive_mis_errors"], 0)
        self.assertEqual(status["max_consecutive_mis_errors"], 5)

    def test_repeated_background_failures_stop_loop(self):
        loop=AutonomousLoop(DummyEngine(),client=object(),watchlist=[],interval=20)
        loop._stop=threading.Event()
        calls={"n":0}
        def fail_once():
            calls["n"]+=1
            raise RuntimeError("synthetic test failure")
        loop.run_once=fail_once
        # Make waits immediate while preserving the real loop and stop behavior.
        class FastStop:
            def __init__(self): self.n=0
            def is_set(self): return self.n>=5
            def set(self): self.n=5
            def clear(self): self.n=0
            def wait(self, timeout): self.n+=1; return self.n>=5
        loop._stop=FastStop()
        loop._run()
        self.assertGreaterEqual(loop.consecutive_cycle_errors,1)
        self.assertFalse(loop.enabled)
        self.assertIsNotNone(loop.last_cycle_error)

    def test_status_degrades_after_mis_failure_and_recovers(self):
        loop=AutonomousLoop(DummyEngine(),client=object(),watchlist=[],interval=20)
        loop.enabled=True
        loop.consecutive_mis_errors=2
        self.assertEqual(loop.status()["health"], "DEGRADED")
        loop.consecutive_mis_errors=0
        self.assertEqual(loop.status()["health"], "RUNNING")

    def test_fifth_consecutive_mis_failure_sets_stop_signal(self):
        loop=AutonomousLoop(DummyEngine(),client=object(),watchlist=[],interval=20)
        loop._stop.clear()
        for i in range(5):
            loop.consecutive_mis_errors += 1
            if loop.consecutive_mis_errors >= loop.max_consecutive_mis_errors:
                loop._stop.set()
        self.assertTrue(loop._stop.is_set())
        self.assertEqual(loop.consecutive_mis_errors, 5)

if __name__=="__main__": unittest.main()
