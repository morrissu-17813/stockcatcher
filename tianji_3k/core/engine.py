from dataclasses import asdict
from ..models.signal import ThreeKSignal
from ..strategy.three_k import evaluate_three_k
from .stages import stage0_data_gate, stage1_direction, stage2_breakout


class Tianji3KEngine:
    """Tianji 3K V1.0 pipeline: Stage 0 -> 1 -> 2 -> 3."""

    def run(self, snapshot: dict) -> ThreeKSignal:
        gate = stage0_data_gate(snapshot)
        if not gate["passed"]:
            return ThreeKSignal(status="REJECT", reason=gate["reason"])

        direction = stage1_direction(snapshot)
        breakout = stage2_breakout(snapshot)
        decision = evaluate_three_k(snapshot, direction, breakout)

        return ThreeKSignal(
            status=decision["status"],
            score=decision["score"],
            reason=decision["reason"],
            symbol=snapshot.get("symbol"),
            metadata={
                "stage0": gate,
                "stage1": direction,
                "stage2": breakout,
            },
        )
