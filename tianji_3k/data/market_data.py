from dataclasses import dataclass
from typing import Optional


@dataclass
class MarketSnapshot:
    symbol: str
    close: float
    volume: float
    prev_close: float
    high: float
    prev_high: float
    prev2_high: float
    prev_volume: Optional[float] = None
    week_kd_golden_cross: bool = False
    day_kd_up: bool = False
