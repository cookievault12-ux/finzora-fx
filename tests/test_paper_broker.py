"""Unit tests for PaperBroker.

These mirror the manual verification run during development (market fills,
unrealized P&L, position close, limit-order triggering, stop-loss
triggering, slippage/commission) — see the commit history for that
verification run's output, since pytest itself wasn't installable in the
sandbox this was built in (no outbound package-index access). Run this for
real with: pip install -e ".[dev]" && pytest tests/test_paper_broker.py -v
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from src.brokers.types import OrderSide, OrderType, PositionDirection
from src.market.types import Quote
from src.paper_trading.paper_broker import PaperBroker, PaperBrokerConfig


class FakeQuoteFeed:
    """Test double for a MarketDataProvider price feed — a mutable dict of
    current quotes, so tests can move the market between calls."""

    def __init__(self, initial: dict[str, Quote]):
        self._quotes = dict(initial)

    def __call__(self, instrument: str) -> Quote:
        return self._quotes[instrument]

    def set(self, instrument: str, bid: str, ask: str) -> Quote:
        q = Quote(
            instrument=instrument,
            ts=dt.datetime.now(dt.timezone.utc),
            bid=Decimal(bid),
            ask=Decimal(ask),
            provider="fake",
        )
        self._quotes[instrument] = q
        return q


@pytest.fixture
def feed() -> FakeQuoteFeed:
    return FakeQuoteFeed({"EUR/USD": Quote(
        instrument="EUR/USD", ts=dt.datetime.now(dt.timezone.utc),
        bid=Decimal("1.1000"), ask=Decimal("1.1002"), provider="fake",
    )})


@pytest.fixture
def broker(feed: FakeQuoteFeed) -> PaperBroker:
    return PaperBroker(
        get_quote=feed,
        config=PaperBrokerConfig(starting_capital=Decimal("10000"), slippage_bps=Decimal("0"), commission_bps=Decimal("0")),
    )


def test_starting_account_matches_config(broker: PaperBroker):
    acct = broker.get_account()
    assert acct.equity == Decimal("10000")
    assert acct.cash == Decimal("10000")
    assert acct.unrealized_pnl == Decimal("0")


def test_market_buy_fills_at_ask(broker: PaperBroker):
    order = broker.submit_order("EUR/USD", OrderSide.BUY, OrderType.MARKET, Decimal("10000"))
    assert order.status.value == "FILLED"
    assert order.avg_fill_price == Decimal("1.1002")
    positions = broker.get_positions()
    assert len(positions) == 1
    assert positions[0].direction == PositionDirection.LONG
    assert positions[0].quantity == Decimal("10000")


def test_unrealized_pnl_tracks_market_moves(broker: PaperBroker, feed: FakeQuoteFeed):
    broker.submit_order("EUR/USD", OrderSide.BUY, OrderType.MARKET, Decimal("10000"))
    feed.set("EUR/USD", "1.1100", "1.1102")
    acct = broker.get_account()
    expected = (Decimal("1.1100") - Decimal("1.1002")) * Decimal("10000")
    assert acct.unrealized_pnl == expected


def test_close_position_realizes_pnl(broker: PaperBroker, feed: FakeQuoteFeed):
    broker.submit_order("EUR/USD", OrderSide.BUY, OrderType.MARKET, Decimal("10000"))
    feed.set("EUR/USD", "1.1100", "1.1102")
    expected = (Decimal("1.1100") - Decimal("1.1002")) * Decimal("10000")

    close_order = broker.close_position("EUR/USD")

    assert close_order.status.value == "FILLED"
    assert broker.get_positions() == []
    assert len(broker.closed_trades) == 1
    assert broker.closed_trades[0].pnl == expected
    assert broker.get_account().cash == Decimal("10000") + expected


def test_limit_order_stays_pending_until_price_reached(broker: PaperBroker, feed: FakeQuoteFeed):
    order = broker.submit_order("EUR/USD", OrderSide.BUY, OrderType.LIMIT, Decimal("5000"), price=Decimal("1.0990"))
    assert order.status.value == "PENDING"

    broker.on_price_update(feed("EUR/USD"))  # market hasn't moved, still above limit
    assert order.status.value == "PENDING"

    triggering_quote = feed.set("EUR/USD", "1.0985", "1.0989")
    broker.on_price_update(triggering_quote)
    assert order.status.value == "FILLED"


def test_stop_loss_closes_position_on_touch(broker: PaperBroker, feed: FakeQuoteFeed):
    broker.submit_order(
        "EUR/USD", OrderSide.BUY, OrderType.MARKET, Decimal("10000"), stop_loss=Decimal("1.0950")
    )
    losing_quote = feed.set("EUR/USD", "1.0940", "1.0944")

    broker.on_price_update(losing_quote)

    assert broker.get_positions() == []
    assert broker.closed_trades[-1].exit_reason == "SL"
    assert broker.closed_trades[-1].pnl < 0


def test_slippage_and_commission_are_applied(feed: FakeQuoteFeed):
    broker = PaperBroker(
        get_quote=feed,
        config=PaperBrokerConfig(starting_capital=Decimal("10000"), slippage_bps=Decimal("10"), commission_bps=Decimal("5")),
    )
    order = broker.submit_order("EUR/USD", OrderSide.BUY, OrderType.MARKET, Decimal("10000"))

    expected_fill = Decimal("1.1002") * (1 + Decimal("10") / Decimal("10000"))
    assert order.avg_fill_price == expected_fill

    expected_commission = expected_fill * Decimal("10000") * Decimal("5") / Decimal("10000")
    assert broker.get_account().cash == Decimal("10000") - expected_commission


def test_cancel_pending_order(broker: PaperBroker):
    order = broker.submit_order("EUR/USD", OrderSide.BUY, OrderType.LIMIT, Decimal("1000"), price=Decimal("1.0500"))
    broker.cancel_order(order.id)
    assert order.status.value == "CANCELLED"


def test_modify_rejects_filled_order(broker: PaperBroker):
    order = broker.submit_order("EUR/USD", OrderSide.BUY, OrderType.MARKET, Decimal("1000"))
    with pytest.raises(ValueError):
        broker.modify_order(order.id, price=Decimal("1.2000"))
