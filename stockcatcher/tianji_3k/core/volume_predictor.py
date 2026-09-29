from dataclasses import dataclass
from datetime import datetime,time

@dataclass(frozen=True)
class VolumeProjection:
    elapsed_minutes:float
    projected_volume_lots:float
    projected_ratio:float|None
    baseline_start:str
    baseline_end:str
    ready:bool

class IntradayVolumePredictor:
    def __init__(self,session_start=time(9,0),session_end=time(13,30)):
        self.session_start=session_start; self.session_end=session_end
    def project(self,cumulative_volume_lots,observed_at,vma5_lots,min_elapsed_minutes:float=5.0):
        start=datetime.combine(observed_at.date(),self.session_start,observed_at.tzinfo)
        end=datetime.combine(observed_at.date(),self.session_end,observed_at.tzinfo)
        elapsed=max(0,min((observed_at-start).total_seconds()/60,(end-start).total_seconds()/60))
        total=max(1,(end-start).total_seconds()/60)
        ready = elapsed >= min_elapsed_minutes and elapsed > 0
        projected = cumulative_volume_lots*total/elapsed if ready else 0.0
        ratio=projected/vma5_lots if ready and vma5_lots and vma5_lots>0 else None
        return VolumeProjection(elapsed,projected,ratio,start.isoformat(),end.isoformat(),ready)
