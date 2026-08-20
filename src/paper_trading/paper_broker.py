"""PaperBroker — simulated execution implementing BrokerAdapter (spec section 44).

Design notes / known simplifications (documented rather than hidden, per the
project's "no fabricated results" principle — this applies to code honesty
as much as backtest numbers):

- One position per instrument (netted), not per-order. Opposite-direction
  fills reduce/close/flip the existing position rather than being tracked
  as independent hedged positions.
- A single take_profit/stop_loss per position. TP1/TP2/TP3 (spec section 38)
  is not yet implemented here — that needs multiple reduce-only child orders
  layered on top of this, planned for Phase 5.
- Partial fills are modeled as a single partial fill at submission time
  (quantity above `max_single_fill_size` fills partially, remainder is
  dropped rather than queued) — a real partial-fill/continuation queue is
  future work, not silently pretended to exist.
- Margin/leverage is not modeled (`margin_used` is always 0); this is a
  cash-accounting simulator for now, adequate for FX at modest position
  sizes but not a margin-call simulator.
- Financing is a simple daily accrual at a configurable annual rate,
  applied once per call to `apply_daily_financing` — the caller (a
  scheduled job) decides when "once per day" actually happens.

This broker never accepts a live order: it has no live-trading code path at
all, so the trading_mode/live_trading_enabled/manual-authorization gate
(spec section 45) doesn't need to be re-checked here — there is nothing
for it to gate.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from typing import Callable

from src.brokers.base import BrokerAdapter
from src.brokers.types import (
    Account,
    ClosedTrade,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    Position,
    PositionDirection,
)
from src.market.types import Quote


@dataclass
class PaperBrokerConfig:
    starting_capital: Decimal = Decimal("10000")
    base_currency: str = "SGD"
    slippage_bps: Decimal = Decimal("0.5")  # adverse slippage applied to fills, in basis points of price
    commission_bps: Decimal = Decimal("0.2")  # of notional, charged on every fill
    financing_annual_rate: Decimal = Decimal("0.02")  # simple annualized rate applied to notional held overnight
    max_single_fill_size: Decimal = Decimal("1000000")  # above this, a market order partially fills


class PaperBroker(BrokerAdapter):
    name = "PaperBroker"

    def __init__(self, get_quote: Callable[[str], Quote], config: PaperBrokerConfig | None = None):
        """
        get_quote: callable returning the current Quote (bid/ask) for an
        instrument. Injected rather than owned, so PaperBroker never depends
        on a specific MarketDataProvider — tests can pass a stub.
        """
        self._get_quote = get_quote
        self.config = config or PaperBrokerConfig()
        self._cash = self.config.starting_capital
        self._positions: dict[str, Position] = {}
        self._orders: dict[str, Order] = {}
        self.closed_trades: list[ClosedTrade] = []

    # -- internal helpers -------------------------------------------------

    def _apply_slippage(self, price: Decimal, side: OrderSide) -> Decimal:
        factor = self.config.slippage_bps / Decimal("10000")
        return price * (1 + factor) if side is OrderSide.BUY else price * (1 - factor)

    def _commission_for(self, price: Decimal, quantity: Decimal) -> Decimal:
        notional = price * quantity
        return notional * (self.config.commission_bps / Decimal("10000"))

    def _fill_market(self, order: Order) -> Order:
        quote = self._get_quote(order.instrument)
        raw_price = quote.ask if order.side is OrderSide.BUY else quote.bid
        fill_price = self._apply_slippage(raw_price, order.side)
        fill_qty = min(order.quantity, self.config.max_single_fill_size)

        commission = self._commission_for(fill_price, fill_qty)
        self._cash -= commission

        self._apply_fill_to_position(order.instrument, order.side, fill_qty, fill_price, order)

        order.filled_quantity = fill_qty
        order.avg_fill_price = fill_price
        order.filled_at = dt.datetime.now(dt.timezone.utc)
        order.status = (
            OrderStatus.FILLED if fill_qty == order.quantity else OrderStatus.PARTIALLY_FILLED
        )
        return order

    def _apply_fill_to_position(
        self, instrument: str, side: OrderSide, quantity: Decimal, price: Decimal, order: Order
    ) -> None:
        direction = PositionDirection.LONG if side is OrderSide.BUY else PositionDirection.SHORT
        existing = self._positions.get(instrument)

        if existing is None:
            self._positions[instrument] = Position(
                instrument=instrument,
                direction=direction,
                quantity=quantity,
                avg_entry_price=price,
                stop_loss=order.stop_loss,
                take_profit=order.take_profit,
            )
            return

        if existing.direction == direction:
            # adding to the same side: weighted-average entry price
            total_qty = existing.quantity + quantity
            existing.avg_entry_price = (
                existing.avg_entry_price * existing.quantity + price * quantity
            ) / total_qty
            existing.quantity = total_qty
            if order.stop_loss is not None:
                existing.stop_loss = order.stop_loss
            if order.take_profit is not None:
                existing.take_profit = order.take_profit
            return

        # opposite side: reduce, close, or flip
        if quantity < existing.quantity:
            self._realize_partial_close(existing, quantity, price, reason="MANUAL")
            existing.quantity -= quantity
        elif quantity == existing.quantity:
            self._realize_partial_close(existing, quantity, price, reason="MANUAL")
            del self._positions[instrument]
        else:
            self._realize_partial_close(existing, existing.quantity, price, reason="MANUAL")
            flipped_qty = quantity - existing.quantity
            self._positions[instrument] = Position(
                instrument=instrument,
                direction=direction,
                quantity=flipped_qty,
                avg_entry_price=price,
                stop_loss=order.stop_loss,
                take_profit=order.take_profit,
            )

    def _realize_partial_close(
        self, position: Position, quantity: Decimal, exit_price: Decimal, reason: str
    ) -> None:
        if position.direction is PositionDirection.LONG:
            pnl = (exit_price - position.avg_entry_price) * quantity
        else:
            pnl = (position.avg_entry_price - exit_price) * quantity
        self._cash += pnl
        self.closed_trades.append(
            ClosedTrade(
                instrument=position.instrument,
                direction=position.direction,
                entry_price=position.avg_entry_price,
                exit_price=exit_price,
                quantity=quantity,
                opened_at=position.opened_at,
                closed_at=dt.datetime.now(dt.timezone.utc),
                pnl=pnl,
                exit_reason=reason,
                commission=Decimal("0"),  # commission already debited at fill time
                slippage=Decimal("0"),  # embedded in exit_price already
                financing_cost=Decimal("0"),  # accrued separately via apply_daily_financing
            )
        )

    # -- BrokerAdapter interface ------------------------------------------

    def get_account(self) -> Account:
        unrealized = Decimal("0")
        for instrument, pos in self._positions.items():
            quote = self._get_quote(instrument)
            mark = quote.bid if pos.direction is PositionDirection.LONG else quote.ask
            if pos.direction is PositionDirection.LONG:
                unrealized += (mark - pos.avg_entry_price) * pos.quantity
            else:
                unrealized += (pos.avg_entry_price - mark) * pos.quantity
        return Account(
            account_id="paper",
            currency=self.config.base_currency,
            equity=self._cash + unrealized,
            cash=self._cash,
            unrealized_pnl=unrealized,
            margin_used=Decimal("0"),
        )

    def get_instruments(self) -> list[str]:
        return sorted(self._positions.keys())

    def get_prices(self, instruments: list[str]) -> dict[str, tuple[Decimal, Decimal]]:
        result = {}
        for instrument in instruments:
            q = self._get_quote(instrument)
            result[instrument] = (q.bid, q.ask)
        return result

    def get_positions(self) -> list[Position]:
        return list(self._positions.values())

    def get_orders(self) -> list[Order]:
        return list(self._orders.values())

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
        order = Order(
            instrument=instrument,
            side=side,
            order_type=order_type,
            quantity=quantity,
            price=price,
            stop_loss=stop_loss,
            take_profit=take_profit,
        )
        if order_type is OrderType.MARKET:
            self._fill_market(order)
        else:
            if price is None:
                order.status = OrderStatus.REJECTED
            # LIMIT/STOP orders stay PENDING until on_price_update triggers them.
        self._orders[order.id] = order
        return order

    def modify_order(self, order_id: str, **changes) -> Order:
        order = self._orders.get(order_id)
        if order is None:
            raise LookupError(f"No such order: {order_id}")
        if order.status not in (OrderStatus.PENDING, OrderStatus.PARTIALLY_FILLED):
            raise ValueError(f"Cannot modify order in status {order.status}")
        for field_name in ("price", "stop_loss", "take_profit", "quantity"):
            if field_name in changes:
                setattr(order, field_name, changes[field_name])
        return order

    def cancel_order(self, order_id: str) -> None:
        order = self._orders.get(order_id)
        if order is None:
            raise LookupError(f"No such order: {order_id}")
        if order.status is OrderStatus.PENDING:
            order.status = OrderStatus.CANCELLED

    def close_position(self, instrument: str, quantity: Decimal | None = None) -> Order:
        position = self._positions.get(instrument)
        if position is None:
            raise LookupError(f"No open position for {instrument}")
        close_qty = quantity if quantity is not None else position.quantity
        closing_side = OrderSide.SELL if position.direction is PositionDirection.LONG else OrderSide.BUY
        order = Order(instrument=instrument, side=closing_side, order_type=OrderType.MARKET, quantity=close_qty)
        self._fill_market(order)
        self._orders[order.id] = order
        return order

    # -- simulation loop hooks --------------------------------------------

    def on_price_update(self, quote: Quote) -> None:
        """Call this on every new quote to trigger pending LIMIT/STOP orders
        and check open positions' stop-loss/take-profit levels."""
        self._check_pending_orders(quote)
        self._check_position_exits(quote)

    def _check_pending_orders(self, quote: Quote) -> None:
        for order in list(self._orders.values()):
            if order.status is not OrderStatus.PENDING or order.instrument != quote.instrument:
                continue
            if order.order_type is OrderType.LIMIT:
                triggered = (
                    quote.ask <= order.price
                    if order.side is OrderSide.BUY
                    else quote.bid >= order.price
                )
            elif order.order_type is OrderType.STOP:
                triggered = (
                    quote.ask >= order.price
                    if order.side is OrderSide.BUY
                    else quote.bid <= order.price
                )
            else:
                continue
            if triggered:
                self._fill_market(order)

    def _check_position_exits(self, quote: Quote) -> None:
        position = self._positions.get(quote.instrument)
        if position is None:
            return
        mark = quote.bid if position.direction is PositionDirection.LONG else quote.ask
        hit_tp = position.take_profit is not None and (
            (position.direction is PositionDirection.LONG and mark >= position.take_profit)
            or (position.direction is PositionDirection.SHORT and mark <= position.take_profit)
        )
        hit_sl = position.stop_loss is not None and (
            (position.direction is PositionDirection.LONG and mark <= position.stop_loss)
            or (position.direction is PositionDirection.SHORT and mark >= position.stop_loss)
        )
        if hit_tp or hit_sl:
            reason = "TP" if hit_tp else "SL"
            self._realize_partial_close(position, position.quantity, mark, reason=reason)
            del self._positions[quote.instrument]

    def apply_daily_financing(self) -> None:
        """Accrue one day's financing cost/credit on all open positions.
        Call this once per trading day from a scheduled job."""
        daily_rate = self.config.financing_annual_rate / Decimal("365")
        for position in self._positions.values():
            notional = position.avg_entry_price * position.quantity
            cost = notional * daily_rate
            # Convention: longs pay financing, shorts receive it (simplified —
            # real financing depends on rate differentials, see spec section 24).
            self._cash -= cost if position.direction is PositionDirection.LONG else -cost
