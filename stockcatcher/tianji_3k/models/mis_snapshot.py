from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Optional

@dataclass(frozen=True)
class MISSnapshot:
    symbol: str
    current_price: float
    previous_close: float
    today_open: float
    cumulative_volume: float
    up_pct: float
    is_traded: bool
    observed_at: datetime
    data_identity: str
    name: str = ""
    ask3_volume: float = 0.0

    @property
    def breakout_gain_pct(self) -> float:
        if self.previous_close <= 0:
            return 0.0
        return (self.current_price / self.previous_close - 1.0) * 100.0

    def to_dict(self):
        d = asdict(self)
        d["observed_at"] = self.observed_at.isoformat()
        return d
