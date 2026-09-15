from dataclasses import dataclass, field
from typing import Any


@dataclass
class ThreeKSignal:
    status: str
    score: int = 0
    reason: str = ""
    symbol: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "status": self.status,
            "score": self.score,
            "reason": self.reason,
            "metadata": self.metadata,
        }
