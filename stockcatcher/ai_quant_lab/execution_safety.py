"""Deterministic, broker-free safety primitives for AI Quant Lab paper execution.

These primitives do not place live orders. They model order lifecycle and apply
fail-closed market/risk checks so the same rules can be tested before any broker adapter exists.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Optional


class OrderStatus(str, Enum):
    NEW = "NEW"
    ACCEPTED = "ACCEPTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    UNKNOWN = "UNKNOWN"


@dataclass
class PaperOrder:
    order_id: str
    idempotency_key: str
    symbol: str
    side: str
    quantity: int
    status: OrderStatus = OrderStatus.NEW
    filled_quantity: int = 0
    average_fill_price: Decimal = Decimal("0")
    rejection_reason: Optional[str] = None
    updates: list[dict] = field(default_factory=list)

    @property
    def remaining_quantity(self) -> int:
        return self.quantity - self.filled_quantity

    def accept(self) -> None:
        if self.status != OrderStatus.NEW:
            raise ValueError("order can only be accepted from NEW")
        self.status = OrderStatus.ACCEPTED
        self.updates.append({"status": self.status.value})

    def fill(self, quantity: int, price: Decimal) -> None:
        price = Decimal(str(price))
        if self.status not in (OrderStatus.ACCEPTED, OrderStatus.PARTIALLY_FILLED):
            raise ValueError("fill requires an accepted, open order")
        if quantity <= 0 or quantity > self.remaining_quantity:
            raise ValueError("fill quantity exceeds remaining order quantity")
        if price <= 0:
            raise ValueError("fill price must be positive")
        old_notional = self.average_fill_price * self.filled_quantity
        self.filled_quantity += quantity
        self.average_fill_price = (old_notional + price * quantity) / self.filled_quantity
        self.status = OrderStatus.FILLED if self.remaining_quantity == 0 else OrderStatus.PARTIALLY_FILLED
        self.updates.append({"status": self.status.value, "fill_quantity": quantity,
                             "cumulative_quantity": self.filled_quantity, "fill_price": str(price)})

    def cancel(self) -> None:
        if self.status not in (OrderStatus.ACCEPTED, OrderStatus.PARTIALLY_FILLED):
            raise ValueError("only open orders can be cancelled")
        self.status = OrderStatus.CANCELLED
        self.updates.append({"status": self.status.value, "remaining_quantity": self.remaining_quantity})

    def mark_unknown(self, reason: str) -> None:
        # Unknown means reconcile before retrying; never blindly resubmit.
        if self.status in (OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED):
            raise ValueError("terminal order cannot become UNKNOWN")
        self.status = OrderStatus.UNKNOWN
        self.rejection_reason = str(reason)[:240]
        self.updates.append({"status": self.status.value, "reason": self.rejection_reason})


class OrderRegistry:
    """In-process idempotency guard. Production durability must use the Supabase ledger."""
    def __init__(self):
        self.by_key: dict[str, PaperOrder] = {}

    def create(self, order: PaperOrder) -> tuple[PaperOrder, bool]:
        key = order.idempotency_key.strip()
        if not key:
            raise ValueError("idempotency_key is required")
        prior = self.by_key.get(key)
        if prior is not None:
            return prior, False
        self.by_key[key] = order
        return order, True


def market_data_block_reason(snapshot: dict | None, *, max_age_seconds: float = 120.0,
                             now: datetime | None = None) -> str | None:
    """Validate a supplied snapshot; absent snapshots remain valid for explicit manual paper tests."""
    if snapshot is None:
        return None
    if not isinstance(snapshot, dict):
        return "MARKET_SNAPSHOT_INVALID"
    if snapshot.get("stale") is True:
        return "MARKET_DATA_STALE"
    age = snapshot.get("data_age_seconds")
    if age is not None:
        try:
            if float(age) < 0 or float(age) > max_age_seconds:
                return "MARKET_DATA_AGE_LIMIT"
        except (TypeError, ValueError):
            return "MARKET_DATA_AGE_INVALID"
    observed = snapshot.get("observed_at") or snapshot.get("market_timestamp")
    # Provider-calculated age is authoritative when present; timestamps can represent
    # the last market update during after-hours and should not override a validated age.
    if observed and age is None:
        try:
            stamp = datetime.fromisoformat(str(observed).replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
            reference = now or datetime.now(timezone.utc)
            age_seconds = (reference - stamp.astimezone(timezone.utc)).total_seconds()
            if age_seconds < -5:
                return "MARKET_TIMESTAMP_IN_FUTURE"
            if age_seconds > max_age_seconds:
                return "MARKET_TIMESTAMP_STALE"
        except (TypeError, ValueError, OverflowError):
            return "MARKET_TIMESTAMP_INVALID"
    return None


def calculate_slippage(reference_price: Decimal, fill_price: Decimal, side: str) -> dict:
    """Return signed and adverse slippage; positive adverse_bps means worse execution."""
    reference_price, fill_price = Decimal(str(reference_price)), Decimal(str(fill_price))
    if reference_price <= 0 or fill_price <= 0 or side not in ("BUY", "SELL"):
        raise ValueError("valid positive prices and BUY/SELL side are required")
    signed = (fill_price - reference_price) / reference_price * Decimal("10000")
    adverse = signed if side == "BUY" else -signed
    return {"reference_price": str(reference_price), "fill_price": str(fill_price),
            "signed_bps": str(signed.quantize(Decimal("0.01"))),
            "adverse_bps": str(adverse.quantize(Decimal("0.01")))}


def exit_trigger(entry_price: Decimal, mark_price: Decimal, *, stop_loss_pct: Decimal = Decimal("0.02"),
                 take_profit_pct: Decimal = Decimal("0.04")) -> str | None:
    """Long-only paper exit trigger; caller must still pass the exit through risk/persistence."""
    entry_price, mark_price = Decimal(str(entry_price)), Decimal(str(mark_price))
    if entry_price <= 0 or mark_price <= 0 or stop_loss_pct <= 0 or take_profit_pct <= 0:
        raise ValueError("prices and thresholds must be positive")
    if mark_price <= entry_price * (Decimal("1") - stop_loss_pct):
        return "STOP_LOSS"
    if mark_price >= entry_price * (Decimal("1") + take_profit_pct):
        return "TAKE_PROFIT"
    return None
