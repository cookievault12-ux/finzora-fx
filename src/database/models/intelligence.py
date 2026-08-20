"""Macro, central bank, yield, news, and geopolitical intelligence models."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy import BigInteger, ForeignKey, Index, Integer, Numeric, SmallInteger, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.database.base import Base


class MacroEvent(Base):
    __tablename__ = "macro_events"
    __table_args__ = (Index("idx_macro_events_lookup", "currency", "ts"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    event_name: Mapped[str] = mapped_column(String, nullable=False)
    country: Mapped[str] = mapped_column(String, nullable=False)
    currency: Mapped[str] = mapped_column(String, nullable=False)
    ts: Mapped[dt.datetime] = mapped_column(nullable=False)
    actual: Mapped[Decimal | None] = mapped_column(Numeric(24, 8))
    forecast: Mapped[Decimal | None] = mapped_column(Numeric(24, 8))
    previous: Mapped[Decimal | None] = mapped_column(Numeric(24, 8))
    surprise: Mapped[Decimal | None] = mapped_column(Numeric(24, 8))
    importance: Mapped[str | None] = mapped_column(String)
    source: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(nullable=False)


class CentralBankEvent(Base):
    __tablename__ = "central_bank_events"
    __table_args__ = (Index("idx_central_bank_events_lookup", "central_bank", "ts"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    central_bank: Mapped[str] = mapped_column(String, nullable=False)  # FED/ECB/BOE/BOJ/SNB/RBA/RBNZ/BOC/MAS
    event_type: Mapped[str] = mapped_column(String, nullable=False)  # RATE_DECISION/MINUTES/SPEECH/MPS
    ts: Mapped[dt.datetime] = mapped_column(nullable=False)
    policy_rate: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))  # null for MAS (band policy, not a rate)
    stance_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))  # CentralBankStanceScore, -1..+1
    forward_guidance_summary: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(nullable=False)


class YieldData(Base):
    __tablename__ = "yield_data"
    __table_args__ = (
        UniqueConstraint("country", "tenor", "ts", "source"),
        Index("idx_yield_data_lookup", "country", "tenor", "ts"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    country: Mapped[str] = mapped_column(String, nullable=False)
    tenor: Mapped[str] = mapped_column(String, nullable=False)  # 2Y/5Y/10Y
    ts: Mapped[dt.datetime] = mapped_column(nullable=False)
    yield_value: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False)
    source: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(nullable=False)


class NewsArticle(Base):
    __tablename__ = "news_articles"
    __table_args__ = (Index("idx_news_articles_published", "published_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source: Mapped[str] = mapped_column(String, nullable=False)
    source_tier: Mapped[int] = mapped_column(SmallInteger, nullable=False)  # 1 (official) .. 4 (unverified)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[dt.datetime] = mapped_column(nullable=False)
    currencies_mentioned: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    sentiment_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    ingested_at: Mapped[dt.datetime] = mapped_column(nullable=False)


class GeopoliticalEvent(Base):
    __tablename__ = "geopolitical_events"
    __table_args__ = (Index("idx_geopolitical_events_ts", "ts"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    countries_involved: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    currencies_affected: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    event_severity: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    currency_relevance: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    economic_relevance: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    historical_sensitivity: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    expected_duration_days: Mapped[int | None] = mapped_column(Integer)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    geopolitical_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    source_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_quality: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    ts: Mapped[dt.datetime] = mapped_column(nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(nullable=False)
