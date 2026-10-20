"""Deterministic paper-trading ledger. No broker integration or live order path."""
from __future__ import annotations
from dataclasses import dataclass, asdict
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal

Side = Literal["BUY", "SELL"]

def money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

@dataclass(frozen=True)
class Fill:
    symbol: str
    side: Side
    quantity: int
    price: Decimal
    fee: Decimal
    realized_pnl: Decimal

@dataclass
class Position:
    symbol: str
    quantity: int = 0
    average_price: Decimal = Decimal("0")

class PaperLedger:
    """Small, auditable long-only paper ledger; deliberately independent of production."""
    def __init__(self, initial_cash: Decimal = Decimal("1000000"), fee_rate: Decimal = Decimal("0.001425")):
        if initial_cash <= 0:
            raise ValueError("initial_cash must be positive")
        if fee_rate < 0:
            raise ValueError("fee_rate cannot be negative")
        self.initial_cash = money(initial_cash)
        self.cash = self.initial_cash
        self.fee_rate = fee_rate
        self.positions: dict[str, Position] = {}
        self.fills: list[Fill] = []

    def execute(self, symbol: str, side: Side, quantity: int, price: Decimal, *,
                fee_override: Decimal | None = None) -> Fill:
        """Execute a simulated fill; fee_override is only for persisted-fill replay."""
        symbol = symbol.strip().upper()
        price = Decimal(price)
        if not symbol:
            raise ValueError("symbol is required")
        if side not in ("BUY", "SELL"):
            raise ValueError("side must be BUY or SELL")
        if quantity <= 0:
            raise ValueError("quantity must be positive")
        if price <= 0:
            raise ValueError("price must be positive")

        position = self.positions.setdefault(symbol, Position(symbol=symbol))
        notional = money(price * quantity)
        fee = money(notional * self.fee_rate) if fee_override is None else money(Decimal(fee_override))
        if fee < 0:
            raise ValueError("fee cannot be negative")
        realized = Decimal("0")

        if side == "BUY":
            total_cost = notional + fee
            if total_cost > self.cash:
                raise ValueError("insufficient paper cash")
            old_qty = position.quantity
            new_qty = old_qty + quantity
            # Include entry commission in cost basis so P&L reconciles to cash + holdings.
            position.average_price = (position.average_price * old_qty + notional + fee) / new_qty
            position.quantity = new_qty
            self.cash = money(self.cash - total_cost)
        else:
            if quantity > position.quantity:
                raise ValueError("cannot sell more than current long position")
            cost_basis = position.average_price * quantity
            realized = money(notional - fee - cost_basis)
            self.cash = money(self.cash + notional - fee)
            position.quantity -= quantity
            if position.quantity == 0:
                position.average_price = Decimal("0")

        fill = Fill(symbol, side, quantity, price, fee, realized)
        self.fills.append(fill)
        return fill

    def snapshot(self, marks: dict[str, Decimal] | None = None) -> dict:
        marks = marks or {}
        market_value = Decimal("0")
        unrealized = Decimal("0")
        positions = []
        for symbol, pos in sorted(self.positions.items()):
            mark = Decimal(marks.get(symbol, pos.average_price))
            value = mark * pos.quantity
            pnl = (mark - pos.average_price) * pos.quantity
            market_value += value
            unrealized += pnl
            positions.append({
                "symbol": symbol,
                "quantity": pos.quantity,
                "average_price": str(money(pos.average_price)),
                "mark_price": str(money(mark)),
                "market_value": str(money(value)),
                "unrealized_pnl": str(money(pnl)),
            })
        realized = sum((f.realized_pnl for f in self.fills), Decimal("0"))
        equity = self.cash + market_value
        return {
            "initial_cash": str(self.initial_cash),
            "cash": str(money(self.cash)),
            "market_value": str(money(market_value)),
            "equity": str(money(equity)),
            "realized_pnl": str(money(realized)),
            "unrealized_pnl": str(money(unrealized)),
            "total_pnl": str(money(equity - self.initial_cash)),
            "positions": positions,
            "fills": [
                {**asdict(fill), "price": str(fill.price), "fee": str(fill.fee), "realized_pnl": str(fill.realized_pnl)}
                for fill in self.fills
            ],
        }
