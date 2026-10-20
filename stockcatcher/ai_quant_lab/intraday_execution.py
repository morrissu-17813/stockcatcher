"""Central fail-closed entry gate shared by replay and future live integrations.

This module computes permission and position size only. It does not connect to a
broker, persist orders, or submit any order. Callers must perform durable atomic
commit and broker reconciliation before using an equivalent gate in live mode.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, time, timezone, timedelta
from decimal import Decimal, ROUND_FLOOR
from typing import Any

TAIPEI = timezone(timedelta(hours=8))


@dataclass(frozen=True)
class EntryPolicy:
    min_projected_ratio: Decimal = Decimal("2.3")
    max_trigger_age_seconds: float = 300.0
    max_snapshot_age_seconds: float = 30.0
    max_order_notional: Decimal = Decimal("100000")
    commission_rate: Decimal = Decimal("0.001425")
    max_positions: int = 3
    max_daily_loss_pct: Decimal = Decimal("0.02")
    entry_cutoff: time = time(13, 20, 0)


@dataclass(frozen=True)
class EntryContext:
    persistence_ready: bool
    market_data_ready: bool
    cash: Decimal
    open_symbols: frozenset[str] = frozenset()
    traded_symbols_today: frozenset[str] = frozenset()
    open_position_count: int = 0
    daily_loss_pct: Decimal = Decimal("0")  # positive fraction, e.g. 0.02 = 2% loss


def evaluate_entry(signal: dict[str, Any], context: EntryContext,
                   policy: EntryPolicy | None = None) -> tuple[bool, str]:
    """Return (allowed, reason). Any missing critical evidence fails closed."""
    policy = policy or EntryPolicy()
    if not context.persistence_ready:
        return False, "PERSISTENCE_NOT_READY"
    if not context.market_data_ready:
        return False, "MARKET_DATA_NOT_READY"
    stamp = signal.get("timestamp")
    if not stamp:
        return False, "SIGNAL_TIMESTAMP_MISSING"
    try:
        dt = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            local = dt.time()
        else:
            local = dt.astimezone(TAIPEI).timetz().replace(tzinfo=None)
    except (ValueError, TypeError):
        return False, "SIGNAL_TIMESTAMP_INVALID"
    if local < time(9, 0, 0) or local > policy.entry_cutoff:
        return False, "OUTSIDE_ENTRY_WINDOW"
    if signal.get("evidence") != "FUGLE_5M":
        return False, "REQUIRES_FUGLE_5M_CONFIRMATION"
    if signal.get("level") != "STRONG":
        return False, "REQUIRES_STRONG_LEVEL"
    projected = signal.get("projected_ratio")
    if projected is None:
        return False, "PROJECTED_VOLUME_MISSING"
    try:
        if Decimal(str(projected)) < policy.min_projected_ratio:
            return False, "PROJECTED_VOLUME_BELOW_THRESHOLD"
    except Exception:
        return False, "PROJECTED_VOLUME_INVALID"
    price, breakout = signal.get("price"), signal.get("breakout_price")
    if price is None or breakout is None:
        return False, "PRICE_OR_BREAKOUT_MISSING"
    try:
        price, breakout = Decimal(str(price)), Decimal(str(breakout))
        if price <= 0 or breakout <= 0:
            return False, "PRICE_OR_BREAKOUT_INVALID"
        if price <= breakout:
            return False, "PRICE_NOT_ABOVE_BREAKOUT"
    except Exception:
        return False, "PRICE_OR_BREAKOUT_INVALID"
    trigger_age = signal.get("trigger_age_s")
    if trigger_age is None:
        return False, "TRIGGER_AGE_MISSING"
    try:
        if float(trigger_age) < 0 or float(trigger_age) > policy.max_trigger_age_seconds:
            return False, "TRIGGER_EXPIRED"
    except Exception:
        return False, "TRIGGER_AGE_INVALID"
    quote_age = signal.get("snapshot_received_age_s")
    if quote_age is None:
        return False, "SNAPSHOT_AGE_MISSING"
    try:
        if float(quote_age) < 0 or float(quote_age) > policy.max_snapshot_age_seconds:
            return False, "SNAPSHOT_STALE"
    except Exception:
        return False, "SNAPSHOT_AGE_INVALID"
    symbol = str(signal.get("symbol") or "").strip()
    if not symbol:
        return False, "SYMBOL_MISSING"
    if symbol in context.open_symbols or symbol in context.traded_symbols_today:
        return False, "DUPLICATE_POSITION_OR_DAILY_REENTRY"
    if context.open_position_count >= policy.max_positions:
        return False, "MAX_OPEN_POSITIONS"
    if context.daily_loss_pct >= policy.max_daily_loss_pct:
        return False, "DAILY_LOSS_LIMIT"
    if context.cash <= 0:
        return False, "INSUFFICIENT_PAPER_CASH"
    return True, "STRICT_ENTRY_GATE_PASSED"


def size_position(reference_price: Decimal, cash: Decimal,
                  policy: EntryPolicy | None = None, slippage_bps: Decimal = Decimal("10")) -> dict[str, Decimal | int]:
    """Size an isolated paper order in shares; caller applies venue lot/tick constraints."""
    policy = policy or EntryPolicy()
    reference_price, cash = Decimal(str(reference_price)), Decimal(str(cash))
    if reference_price <= 0 or cash <= 0:
        return {"quantity": 0, "fill_price": Decimal("0"), "notional": Decimal("0"), "fee": Decimal("0"), "total_cost": Decimal("0")}
    fill_price = reference_price * (Decimal("1") + Decimal(str(slippage_bps)) / Decimal("10000"))
    allowed_notional = min(policy.max_order_notional, cash / (Decimal("1") + policy.commission_rate))
    qty = int((allowed_notional / fill_price).to_integral_value(rounding=ROUND_FLOOR))
    while qty > 0 and fill_price * qty * (Decimal("1") + policy.commission_rate) > cash:
        qty -= 1
    notional = fill_price * qty
    fee = notional * policy.commission_rate
    return {"quantity": qty, "fill_price": fill_price, "notional": notional, "fee": fee, "total_cost": notional + fee}


def evaluate_exit(entry_fill_price: Decimal, mark_price: Decimal | None, *,
                  quote_age_seconds: float | None, stop_loss_pct: Decimal = Decimal("0.02"),
                  take_profit_pct: Decimal = Decimal("0.04"), max_snapshot_age_seconds: float = 30.0) -> tuple[str, str]:
    """Fresh-quote-only exit decision for a long paper position.

    A missing/expired price does not trigger a fabricated fill. Callers must keep
    the position state visible and escalate the data failure while blocking new entries.
    """
    if mark_price is None:
        return "NO_EXIT", "EXIT_PRICE_MISSING"
    if quote_age_seconds is None:
        return "NO_EXIT", "EXIT_QUOTE_AGE_MISSING"
    try:
        age = float(quote_age_seconds)
    except (ValueError, TypeError):
        return "NO_EXIT", "EXIT_QUOTE_AGE_INVALID"
    if age < 0 or age > max_snapshot_age_seconds:
        return "NO_EXIT", "EXIT_QUOTE_STALE"
    try:
        entry = Decimal(str(entry_fill_price)); mark = Decimal(str(mark_price))
        stop = Decimal(str(stop_loss_pct)); target = Decimal(str(take_profit_pct))
    except Exception:
        return "NO_EXIT", "EXIT_PRICE_INVALID"
    if entry <= 0 or mark <= 0 or stop <= 0 or target <= 0:
        return "NO_EXIT", "EXIT_PRICE_INVALID"
    if mark <= entry * (Decimal("1") - stop):
        return "STOP_LOSS", "FRESH_QUOTE_STOP_LOSS_TRIGGERED"
    if mark >= entry * (Decimal("1") + target):
        return "TAKE_PROFIT", "FRESH_QUOTE_TAKE_PROFIT_TRIGGERED"
    return "HOLD", "FRESH_QUOTE_WITHIN_EXIT_BANDS"
