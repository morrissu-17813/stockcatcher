from dataclasses import dataclass, asdict

HARD_PRODUCTS={"ETF","ETN","WARRANT","WARRANTS","PREFERRED","BOND","DR","REIT","CB"}
HARD_MARKETS={"EMERGING","EMERGING_STOCK","興櫃"}
HARD_STATUS={"DISPOSAL","SUSPENDED","ABNORMAL","處置","暫停交易"}

@dataclass(frozen=True)
class SnapshotEligibility:
    symbol:str
    eligible:bool
    exclusion_reason:str|None=None
    product_type:str=""
    market:str=""
    status:str=""
    yesterday_volume_lots:float|None=None
    is_financial:bool=False
    def to_dict(self): return asdict(self)

class SnapshotUniverseFilter:
    # 金融股資料層預設保留；是否排除交給策略設定。
    def __init__(self,min_yesterday_volume_lots=500,exclude_financial=False):
        self.min_yesterday_volume_lots=float(min_yesterday_volume_lots)
        self.exclude_financial=exclude_financial
    def evaluate(self,row):
        norm=lambda x:str(x or "").strip().upper()
        symbol=str(row.get("symbol") or "").strip()
        product=norm(row.get("product_type") or row.get("security_type"))
        market=norm(row.get("market") or row.get("market_type"))
        status=norm(row.get("status") or row.get("trading_status"))
        financial=bool(row.get("is_financial",False))
        try: yvol=float(row.get("yesterday_volume_lots"))
        except (TypeError,ValueError): yvol=None
        reason=None
        if product in HARD_PRODUCTS: reason=f"PRODUCT_{product.replace(' ','_')}"
        elif market in HARD_MARKETS: reason="MARKET_EMERGING"
        elif status in HARD_STATUS: reason=f"STATUS_{status.replace(' ','_')}"
        elif product in {"","UNKNOWN","NONE"}: reason="PRODUCT_UNKNOWN"
        elif self.exclude_financial and financial: reason="SECTOR_FINANCIAL"
        elif yvol is None: reason="VOLUME_UNKNOWN"
        elif yvol < self.min_yesterday_volume_lots: reason="LOW_LIQUIDITY"
        return SnapshotEligibility(symbol,reason is None,reason,product,market,status,yvol,financial)
    def filter_rows(self,rows):
        eligible,audit=[],[]
        for row in rows:
            r=self.evaluate(row)
            (eligible if r.eligible else audit).append(row if r.eligible else r.to_dict())
        return eligible,audit
