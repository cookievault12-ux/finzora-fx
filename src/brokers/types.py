"""Shared broker-side value objects (BrokerAdapter interface, spec section 14)."""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"


class OrderStatus(str, Enum):
    PENDING = "PENDING"
    FILLED = "FILLED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class PositionDirection(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"


@dataclass
class Account:
    account_id: str
    currency: str
    equity: Decimal
    cash: Decimal
    unrealized_pnl: Decimal
    margin_used: Decimal = Decimal("0")


@dataclass
class Order:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    instrument: str = ""
    side: OrderSide = OrderSide.BUY
    order_type: OrderType = OrderType.MARKET
    quantity: Decimal = Decimal("0")
    filled_quantity: Decimal = Decimal("0")
    price: Decimal | None = None  # limit/stop trigger price; None for market
    stop_loss: Decimal | None = None
    take_profit: Decimal | None = None
    status: OrderStatus = OrderStatus.PENDING
    submitted_at: dt.datetime = field(default_factory=lambda: dt.datetime.now(dt.timezone.utc))
    filled_at: dt.datetime | None = None
    avg_fill_price: Decimal | None = None
    broker: str = "PaperBroker"


@dataclass
class Position:
    instrument: str
    direction: PositionDirection
    quantity: Decimal
    avg_entry_price: Decimal
    stop_loss: Decimal | None = None
    take_profit: Decimal | None = None
    unrealized_pnl: Decimal = Decimal("0")
    opened_at: dt.datetime = field(default_factory=lambda: dt.datetime.now(dt.timezone.utc))


@dataclass
class ClosedTrade:
    instrument: str
    direction: PositionDirection
    entry_price: Decimal
    exit_price: Decimal
    quantity: Decimal
    opened_at: dt.datetime
    closed_at: dt.datetime
    pnl: Decimal
    exit_reason: str  # 'TP' | 'SL' | 'MANUAL' | 'TIMEOUT'
    commission: Decimal
    slippage: Decimal
    financing_cost: Decimal
