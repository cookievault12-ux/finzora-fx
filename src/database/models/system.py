"""System health and data-quality event models.

A DataQualityEvent with resulted_in_no_trade=True is the audit trail for
the "bad data -> NO TRADE" rule — never silently repair questionable data.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import BigInteger, Boolean, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.database.base import Base


class SystemEvent(Base):
    __tablename__ = "system_events"
    __table_args__ = (Index("idx_system_events_ts", "ts"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    severity: Mapped[str] = mapped_column(String, nullable=False)  # INFO/WARNING/ERROR/CRITICAL
    component: Mapped[str] = mapped_column(String, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    ts: Mapped[dt.datetime] = mapped_column(nullable=False)
    resolved_at: Mapped[dt.datetime | None] = mapped_column()


class DataQualityEvent(Base):
    __tablename__ = "data_quality_events"
    __table_args__ = (Index("idx_data_quality_events_ts", "ts"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    instrument_id: Mapped[int | None] = mapped_column(ForeignKey("instruments.id"))
    issue_type: Mapped[str] = mapped_column(String, nullable=False)
    timeframe: Mapped[str | None] = mapped_column(String)
    ts: Mapped[dt.datetime] = mapped_column(nullable=False)
    details: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    resulted_in_no_trade: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[dt.datetime] = mapped_column(nullable=False)
