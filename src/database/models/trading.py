"""Paper trading, positions, portfolio, performance, and risk-event models."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy import BigInteger, ForeignKey, Index, Integer, Interval, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.database.base import Base


class PaperOrder(Base):
    __tablename__ = "paper_orders"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    signal_id: Mapped[int | None] = mapped_column(ForeignKey("signals.id"))
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), nullable=False)
    order_type: Mapped[str] = mapped_column(String, nullable=False)  # MARKET/LIMIT/STOP
    side: Mapped[str] = mapped_column(String, nullable=False)  # BUY/SELL
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    price: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    status: Mapped[str] = mapped_column(String, nullable=False, default="PENDING")
    broker: Mapped[str] = mapped_column(String, nullable=False, default="PaperBroker")
    submitted_at: Mapped[dt.datetime] = mapped_column(nullable=False)
    filled_at: Mapped[dt.datetime | None] = mapped_column()


class PaperTrade(Base):
    __tablename__ = "paper_trades"
    __table_args__ = (Index("idx_paper_trades_instrument", "instrument_id", "opened_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    paper_order_id: Mapped[int | None] = mapped_column(ForeignKey("paper_orders.id"))
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), nullable=False)
    direction: Mapped[str] = mapped_column(String, nullable=False)  # LONG/SHORT
    entry_price: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    exit_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    stop_loss: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    take_profit: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    opened_at: Mapped[dt.datetime] = mapped_column(nullable=False)
    closed_at: Mapped[dt.datetime | None] = mapped_column()
    pnl: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    pnl_pct: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    holding_period: Mapped[dt.timedelta | None] = mapped_column(Interval)
    exit_reason: Mapped[str | None] = mapped_column(String)  # TP1/TP2/TP3/SL/TRAILING/MANUAL/TIMEOUT
    commission: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    slippage: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    financing_cost: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    created_at: Mapped[dt.datetime] = mapped_column(
        nullable=False, default=lambda: dt.datetime.now(dt.timezone.utc)
    )


class Position(Base):
    __tablename__ = "positions"
    __table_args__ = (Index("idx_positions_status", "status"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), nullable=False)
    direction: Mapped[str] = mapped_column(String, nullable=False)  # LONG/SHORT
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    avg_entry_price: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    unrealized_pnl: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    status: Mapped[str] = mapped_column(String, nullable=False, default="OPEN")
    opened_at: Mapped[dt.datetime] = mapped_column(nullable=False)
    updated_at: Mapped[dt.datetime] = mapped_column(nullable=False)


class PortfolioSnapshot(Base):
    __tablename__ = "portfolio_snapshots"
    __table_args__ = (Index("idx_portfolio_snapshots_ts", "ts"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    ts: Mapped[dt.datetime] = mapped_column(nullable=False)
    equity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    cash: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    unrealized_pnl: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    realized_pnl: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    drawdown_pct: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False, default=0)
    currency_exposure: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    open_positions_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[dt.datetime] = mapped_column(
        nullable=False, default=lambda: dt.datetime.now(dt.timezone.utc)
    )


class PerformanceMetric(Base):
    __tablename__ = "performance_metrics"
    __table_args__ = (Index("idx_performance_metrics_period", "period_type", "period_end"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    period_start: Mapped[dt.datetime] = mapped_column(nullable=False)
    period_end: Mapped[dt.datetime] = mapped_column(nullable=False)
    period_type: Mapped[str] = mapped_column(String, nullable=False)  # DAILY/WEEKLY/MONTHLY/ALL_TIME
    cagr: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    sharpe: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    sortino: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    calmar: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    max_drawdown: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    win_rate: Mapped[Decimal | None] = mapped_column(Numeric(6, 4))
    avg_win: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    avg_loss: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    profit_factor: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    expectancy: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    num_trades: Mapped[int | None] = mapped_column(Integer)
    turnover: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    transaction_costs: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    best_month: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    worst_month: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    created_at: Mapped[dt.datetime] = mapped_column(
        nullable=False, default=lambda: dt.datetime.now(dt.timezone.utc)
    )


class RiskEvent(Base):
    __tablename__ = "risk_events"
    __table_args__ = (Index("idx_risk_events_ts", "ts"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    ts: Mapped[dt.datetime] = mapped_column(nullable=False)
    details: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    portfolio_snapshot_id: Mapped[int | None] = mapped_column(ForeignKey("portfolio_snapshots.id"))
    created_at: Mapped[dt.datetime] = mapped_column(
        nullable=False, default=lambda: dt.datetime.now(dt.timezone.utc)
    )
