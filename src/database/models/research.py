"""Backtest, walk-forward, and Monte Carlo run models.

No performance figure is ever reported unless it comes from an actual
recorded run in one of these tables — never invented.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy import BigInteger, ForeignKey, Index, Integer, Numeric, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.database.base import Base


class BacktestRun(Base):
    __tablename__ = "backtest_runs"
    __table_args__ = (Index("idx_backtest_runs_strategy", "strategy_id", "created_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    strategy_id: Mapped[int] = mapped_column(ForeignKey("strategies.id"), nullable=False)
    strategy_version_id: Mapped[int | None] = mapped_column(ForeignKey("strategy_versions.id"))
    instrument_id: Mapped[int | None] = mapped_column(ForeignKey("instruments.id"))
    period_start: Mapped[dt.datetime] = mapped_column(nullable=False)
    period_end: Mapped[dt.datetime] = mapped_column(nullable=False)
    dataset_ref: Mapped[str | None] = mapped_column(Text)
    parameters: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    transaction_assumptions: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    return_pct: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    cagr: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    sharpe: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    sortino: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    max_drawdown: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    win_rate: Mapped[Decimal | None] = mapped_column(Numeric(6, 4))
    profit_factor: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    expectancy: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    num_trades: Mapped[int | None] = mapped_column(Integer)
    costs: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    best_trade: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    worst_trade: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    created_at: Mapped[dt.datetime] = mapped_column(nullable=False)


class WalkForwardRun(Base):
    __tablename__ = "walk_forward_runs"
    __table_args__ = (Index("idx_walk_forward_runs_strategy", "strategy_id", "created_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    strategy_id: Mapped[int] = mapped_column(ForeignKey("strategies.id"), nullable=False)
    train_start: Mapped[dt.datetime] = mapped_column(nullable=False)
    train_end: Mapped[dt.datetime] = mapped_column(nullable=False)
    test_start: Mapped[dt.datetime] = mapped_column(nullable=False)
    test_end: Mapped[dt.datetime] = mapped_column(nullable=False)
    backtest_run_id: Mapped[int | None] = mapped_column(ForeignKey("backtest_runs.id"))
    created_at: Mapped[dt.datetime] = mapped_column(nullable=False)


class MonteCarloRun(Base):
    __tablename__ = "monte_carlo_runs"
    __table_args__ = (Index("idx_monte_carlo_runs_strategy", "strategy_id", "created_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    strategy_id: Mapped[int] = mapped_column(ForeignKey("strategies.id"), nullable=False)
    based_on_backtest_run_id: Mapped[int | None] = mapped_column(ForeignKey("backtest_runs.id"))
    num_simulations: Mapped[int] = mapped_column(Integer, nullable=False)
    probability_of_ruin: Mapped[Decimal | None] = mapped_column(Numeric(6, 4))
    expected_drawdown: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    worst_case_drawdown: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    probability_return_gte_12: Mapped[Decimal | None] = mapped_column(Numeric(6, 4))
    probability_return_gte_15: Mapped[Decimal | None] = mapped_column(Numeric(6, 4))
    probability_drawdown_gt_20: Mapped[Decimal | None] = mapped_column(Numeric(6, 4))
    probability_drawdown_gt_30: Mapped[Decimal | None] = mapped_column(Numeric(6, 4))
    return_distribution: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[dt.datetime] = mapped_column(nullable=False)
