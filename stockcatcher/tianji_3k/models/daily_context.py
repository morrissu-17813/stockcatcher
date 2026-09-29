from dataclasses import dataclass, asdict
from typing import Optional

@dataclass(frozen=True)
class DailyContext:
    symbol: str
    name: str = ""
    exchange: str = ""
    market: str = ""
    industry: str = ""
    as_of_date: str = ""
    prev_close: float = 0.0
    k1_high: float = 0.0
    k2_high: float = 0.0
    breakout_level: float = 0.0
    vma5: float = 0.0
    yesterday_volume: float = 0.0
    ma20: float = 0.0
    ma60: float = 0.0
    stage0_pass: bool = False
    stage1_pass: bool = False
    stage2_pass: bool = False
    stage3_pass: bool = False
    preselected: bool = False
    previous_open: float = 0.0

    def to_dict(self):
        return asdict(self)
