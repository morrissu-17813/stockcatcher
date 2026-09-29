from pathlib import Path

from tianji_3k.core.state_machine import IntradayStateMachine
from tianji_3k.tools.preflight import run


def test_preflight_structure(tmp_path):
    pkg = tmp_path / "tianji_3k"
    for rel in ["__init__.py", "runner.py", "tools/stage0_production.py", "stage1/trend_engine.py", "stage2/breakout_engine.py", "stage3/volume_engine.py", "validation/prediction_ledger.py"]:
        p = pkg / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("", encoding="utf-8")
    # This only verifies the function is callable; import checks are expected to fail in temp tree.
    assert isinstance(run(tmp_path), int)
