from __future__ import annotations
from dataclasses import dataclass, asdict
import hashlib, json
@dataclass(frozen=True)
class MarketSnapshot:
    symbol:str; observed_at:str; current_price:float; previous_close:float; today_open:float; cumulative_volume_shares:int; up_pct:float
    is_traded:bool=True; source:str='MIS'; data_identity:str=''; name:str=''; market:str=''; security_type:str='common_stock'
    @property
    def cumulative_volume_lots(self): return self.cumulative_volume_shares/1000.0
    @property
    def payload_hash(self):
        d={k:v for k,v in asdict(self).items()}; return hashlib.sha256(json.dumps(d,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    @property
    def snapshot_id(self): return f'{self.symbol}:{self.data_identity or self.payload_hash}'
    def to_dict(self):
        d=asdict(self); d.update(cumulative_volume_lots=self.cumulative_volume_lots,payload_hash=self.payload_hash,snapshot_id=self.snapshot_id); return d
def build_snapshot(symbol,raw,name='',market='',security_type='common_stock'):
    observed=raw.get('observed_at'); observed=observed.isoformat() if hasattr(observed,'isoformat') else str(observed)
    # Production MIS exposes explicit LOTS. Legacy/replay payloads may still
    # provide `cumulative_volume` in SHARES, so preserve that compatibility.
    if raw.get('cumulative_volume_shares') is not None:
        volume_shares=float(raw.get('cumulative_volume_shares') or 0)
    elif raw.get('cumulative_volume_lots') is not None:
        volume_shares=float(raw.get('cumulative_volume_lots') or 0)*1000.0
    else:
        volume_shares=float(raw.get('cumulative_volume') or 0)
    return MarketSnapshot(str(symbol),observed,float(raw.get('current_price',0)),float(raw.get('previous_close',0)),float(raw.get('today_open',0)),int(volume_shares),float(raw.get('up_pct',0)),bool(raw.get('is_traded',True)),str(raw.get('source') or 'MIS'),str(raw.get('data_identity') or ''),name or str(raw.get('name') or ''),market or str(raw.get('market') or ''),str(raw.get('security_type') or security_type))
