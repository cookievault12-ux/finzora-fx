"""Market data models: currency pairs, instruments, prices, features, regimes.

Mirrors migrations/sql/0001_initial_schema.sql exactly — if you change one,
change the other, then regenerate an Alembic migration for the delta.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database.base import Base


class CurrencyPair(Base):
    __tablename__ = "currency_pairs"
    __table_args__ = (CheckConstraint("category IN ('MAJOR','CROSS')", name="ck_currency_pairs_category"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    symbol: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    base_currency: Mapped[str] = mapped_column(String, nullable=False)
    quote_currency: Mapped[str] = mapped_column(String, nullable=False)
    category: Mapped[str] = mapped_column(String, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        nullable=False, default=lambda: dt.datetime.now(dt.timezone.utc)
    )


class Instrument(Base):
    __tablename__ = "instruments"
    __table_args__ = (
        CheckConstraint(
            "asset_class IN ('FX','COMMODITY','INDEX','BOND_YIELD','CREDIT_SPREAD','OTHER')",
            name="ck_instruments_asset_class",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    symbol: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    asset_class: Mapped[str] = mapped_column(String, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String)
    is_tradeable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    provider_instrument_ids: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    currency_pair_id: Mapped[int | None] = mapped_column(ForeignKey("currency_pairs.id"))
    created_at: Mapped[dt.datetime] = mapped_column(
        nullable=False, default=lambda: dt.datetime.now(dt.timezone.utc)
    )


class PriceData(Base):
    __tablename__ = "price_data"
    __table_args__ = (
        CheckConstraint("timeframe IN ('1D','4H','1H','15M','5M')", name="ck_price_data_timeframe"),
        UniqueConstraint("instrument_id", "timeframe", "ts", "provider"),
        Index("idx_price_data_lookup", "instrument_id", "timeframe", "ts"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), nullable=False)
    timeframe: Mapped[str] = mapped_column(String, nullable=False)
    ts: Mapped[dt.datetime] = mapped_column(nullable=False)
    open: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    high: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    low: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    close: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    volume: Mapped[Decimal | None] = mapped_column(Numeric(24, 4))
    bid: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    ask: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    spread: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    provider: Mapped[str] = mapped_column(String, nullable=False)
    ingested_at: Mapped[dt.datetime] = mapped_column(nullable=False)


class TickData(Base):
    __tablename__ = "tick_data"
    __table_args__ = (Index("idx_tick_data_lookup", "instrument_id", "ts"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), nullable=False)
    ts: Mapped[dt.datetime] = mapped_column(nullable=False)
    bid: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    ask: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    provider: Mapped[str] = mapped_column(String, nullable=False)
    ingested_at: Mapped[dt.datetime] = mapped_column(nullable=False)


class MarketFeatures(Base):
    __tablename__ = "market_features"
    __table_args__ = (
        UniqueConstraint("instrument_id", "timeframe", "ts", "feature_set_version"),
        Index("idx_market_features_lookup", "instrument_id", "timeframe", "ts"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), nullable=False)
    timeframe: Mapped[str] = mapped_column(String, nullable=False)
    ts: Mapped[dt.datetime] = mapped_column(nullable=False)
    feature_set_version: Mapped[str] = mapped_column(String, nullable=False)
    features: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        nullable=False, default=lambda: dt.datetime.now(dt.timezone.utc)
    )


class CrossAssetData(Base):
    __tablename__ = "cross_asset_data"
    __table_args__ = (
        UniqueConstraint("asset_symbol", "ts", "provider"),
        Index("idx_cross_asset_lookup", "asset_symbol", "ts"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    asset_symbol: Mapped[str] = mapped_column(String, nullable=False)
    ts: Mapped[dt.datetime] = mapped_column(nullable=False)
    value: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    provider: Mapped[str] = mapped_column(String, nullable=False)
    ingested_at: Mapped[dt.datetime] = mapped_column(nullable=False)


class MarketRegime(Base):
    __tablename__ = "market_regimes"
    __table_args__ = (Index("idx_market_regimes_ts", "ts"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    ts: Mapped[dt.datetime] = mapped_column(nullable=False)
    regime_labels: Mapped[list] = mapped_column(JSONB, nullable=False)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    methodology_version: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        nullable=False, default=lambda: dt.datetime.now(dt.timezone.utc)
    )
