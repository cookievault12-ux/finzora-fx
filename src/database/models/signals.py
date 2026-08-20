"""Signal models.

Every signal must be reproducible without querying live data: it snapshots
the instrument, scores, strategy/model versions, and regime it was computed
against, plus a full feature snapshot in SignalFeature.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.database.base import Base


class Signal(Base):
    __tablename__ = "signals"
    __table_args__ = (Index("idx_signals_instrument_ts", "instrument_id", "ts"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    ts: Mapped[dt.datetime] = mapped_column(nullable=False)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), nullable=False)
    direction: Mapped[str] = mapped_column(String, nullable=False)  # LONG/SHORT/NO_TRADE

    entry_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    entry_range_low: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    entry_range_high: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    execution_method: Mapped[str | None] = mapped_column(String)  # MARKET/LIMIT/STOP
    stop_loss: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    take_profit_1: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    take_profit_2: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    take_profit_3: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    risk_reward: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))

    technical_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    macro_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    geopolitical_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    cross_asset_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    regime_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    historical_setup_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    execution_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    risk_reward_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    composite_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))

    p_win: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    p_loss: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    expected_return: Mapped[Decimal | None] = mapped_column(Numeric(8, 6))
    expected_loss: Mapped[Decimal | None] = mapped_column(Numeric(8, 6))
    expected_value: Mapped[Decimal | None] = mapped_column(Numeric(8, 6))
    expected_holding_period: Mapped[str | None] = mapped_column(String)  # e.g. '3 days'
    sample_size: Mapped[int | None] = mapped_column(Integer)

    model_disagreement: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    strategy_id: Mapped[int | None] = mapped_column(ForeignKey("strategies.id"))
    strategy_version_id: Mapped[int | None] = mapped_column(ForeignKey("strategy_versions.id"))
    model_version_id: Mapped[int | None] = mapped_column(ForeignKey("model_versions.id"))
    market_regime_id: Mapped[int | None] = mapped_column(ForeignKey("market_regimes.id"))

    final_decision: Mapped[str] = mapped_column(String, nullable=False)  # LONG/SHORT/NO_TRADE
    reason: Mapped[str | None] = mapped_column(Text)
    llm_analysis: Mapped[dict | None] = mapped_column(JSONB)  # audit trail only — no secrets
    created_at: Mapped[dt.datetime] = mapped_column(nullable=False)


class SignalFeature(Base):
    __tablename__ = "signal_features"
    __table_args__ = (Index("idx_signal_features_signal", "signal_id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    signal_id: Mapped[int] = mapped_column(ForeignKey("signals.id"), nullable=False)
    feature_name: Mapped[str] = mapped_column(String, nullable=False)
    feature_value: Mapped[Decimal | None] = mapped_column(Numeric(24, 10))
    created_at: Mapped[dt.datetime] = mapped_column(nullable=False)
