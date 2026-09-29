class FugleProvider:
    """Adapter placeholder. Connect this to StockCatcher's existing Fugle layer."""

    def get_snapshot(self, symbol: str) -> dict:
        raise NotImplementedError("Connect to existing StockCatcher Fugle provider.")
