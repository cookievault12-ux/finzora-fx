"""BrokerAdapter interface (spec section 14).

PaperBroker implements this first (src/paper_trading/paper_broker.py). Live
brokers (OANDA, Saxo, Interactive Brokers) implement it later, behind the
same interface, so switching from paper to live never touches signal/risk
logic — only the config value that selects which adapter is instantiated.

No implementation of this interface may execute a live order unless
trading_mode == LIVE AND live_trading_enabled == true AND a human has
manually authorized it (spec section 45/99) — that check belongs in the
portfolio/execution orchestration layer, not here, but every adapter must
refuse to silently allow it either.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from decimal import Decimal

from src.brokers.types import Account, Order, OrderSide, OrderType, Position


class BrokerAdapter(ABC):
    name: str  # e.g. 'PaperBroker', 'oanda', 'saxo'

    @abstractmethod
    def get_account(self) -> Account:
        """Return current account snapshot (equity, cash, margin, unrealized P&L)."""

    @abstractmethod
    def get_instruments(self) -> list[str]:
        """Return instruments this broker can trade."""

    @abstractmethod
    def get_prices(self, instruments: list[str]) -> dict[str, tuple[Decimal, Decimal]]:
        """Return {instrument: (bid, ask)} for the requested instruments."""

    @abstractmethod
    def get_positions(self) -> list[Position]:
        """Return all currently open positions."""

    @abstractmethod
    def get_orders(self) -> list[Order]:
        """Return all orders (pending and recently resolved)."""

    @abstractmethod
    def submit_order(
        self,
        instrument: str,
        side: OrderSide,
        order_type: OrderType,
        quantity: Decimal,
        price: Decimal | None = None,
        stop_loss: Decimal | None = None,
        take_profit: Decimal | None = None,
    ) -> Order:
        """Submit a new order. Returns the resulting Order (filled or pending)."""

    @abstractmethod
    def modify_order(self, order_id: str, **changes) -> Order:
        """Modify a pending order's price/stop_loss/take_profit/quantity."""

    @abstractmethod
    def cancel_order(self, order_id: str) -> None:
        """Cancel a pending order."""

    @abstractmethod
    def close_position(self, instrument: str, quantity: Decimal | None = None) -> Order:
        """Close (fully or partially) an open position at current market price."""
