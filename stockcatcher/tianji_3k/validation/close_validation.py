from dataclasses import dataclass


@dataclass
class ValidationResult:
    symbol: str
    predicted_status: str
    actual_close: float | None = None
    actual_high: float | None = None
    success: bool | None = None


def validate(prediction: dict, close_snapshot: dict) -> ValidationResult:
    symbol = prediction.get("symbol", "")
    predicted = prediction.get("status", "UNKNOWN")
    actual_close = close_snapshot.get("close")
    actual_high = close_snapshot.get("high")
    # V1.0: 基礎結果容器；成功定義後續依策略規格細化。
    return ValidationResult(symbol, predicted, actual_close, actual_high, None)
