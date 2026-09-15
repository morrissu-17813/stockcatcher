class MISProvider:
    """Adapter placeholder. Connect this to StockCatcher's existing MIS layer."""

    def get_snapshot(self, symbol: str) -> dict:
        raise NotImplementedError("Connect to existing StockCatcher MIS provider.")
