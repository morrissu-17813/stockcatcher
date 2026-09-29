from typing import Any, Dict, List

class StockCatcherAdapter:
    """優先重用既有 StockCatcher 模組，不複製其 API 實作。"""
    def __init__(self):
        self.scanner=None
        self.technical=None
        try:
            import scanner as scanner_module
            self.scanner=scanner_module
        except Exception:
            pass
        try:
            import technical_indicator_engine as technical_module
            self.technical=technical_module
        except Exception:
            pass

    def fetch_mis_batch_all(self) -> Dict[str, Dict[str, Any]]:
        if not self.scanner or not hasattr(self.scanner,"fetch_mis_batch_all"):
            return {}
        return self.scanner.fetch_mis_batch_all()

    def send_telegram_message(self,text: str, **kwargs):
        if not self.technical or not hasattr(self.technical,"send_telegram_message"):
            raise RuntimeError("既有 technical_indicator_engine.send_telegram_message 不可用")
        return self.technical.send_telegram_message(text, **kwargs)
