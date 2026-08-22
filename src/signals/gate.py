"""NO_TRADE data-quality gate (Phase 4) — checked BEFORE any scoring or
LLM call for an instrument, per spec: an outage or bad data always
defaults to NO_TRADE, and there's no point spending an LLM call on an
instrument whose recent data can't be trusted anyway.

Mirrors src/monitoring/scheduler.py's own resilience pattern (a
DATA_FAILURE SystemEvent is what ingestion/features logging already
writes on failure) — this just reads that same signal back before
generating a signal, rather than duplicating the failure-detection logic.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.database.models.market import Instrument
from src.database.models.system import DataQualityEvent, SystemEvent

# How far back to look for a recent failure before trusting this
# instrument's data enough to generate a signal from it.
LOOKBACK_MINUTES = 90


def has_recent_data_failure(session: Session, instrument: str) -> tuple[bool, str | None]:
    """Returns (blocked, reason). Checks two independent signals: any
    ingestion/feature-computation SystemEvent failure mentioning this
    instrument, and any CRITICAL data_quality_events row (resulted_in_no_trade)
    for it, both within LOOKBACK_MINUTES."""
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=LOOKBACK_MINUTES)

    failure_events = session.execute(
        select(SystemEvent.message, SystemEvent.details)
        .where(
            SystemEvent.event_type == "DATA_FAILURE",
            SystemEvent.component.in_(("ingestion", "features")),
            SystemEvent.ts >= cutoff,
        )
    ).all()
    for message, details in failure_events:
        if details and details.get("instrument") == instrument:
            return True, f"Recent data failure logged: {message}"

    instrument_id = session.scalar(select(Instrument.id).where(Instrument.symbol == instrument))
    if instrument_id is not None:
        critical_issue = session.scalar(
            select(DataQualityEvent.issue_type)
            .where(
                DataQualityEvent.instrument_id == instrument_id,
                DataQualityEvent.resulted_in_no_trade.is_(True),
                DataQualityEvent.ts >= cutoff,
            )
            .limit(1)
        )
        if critical_issue is not None:
            return True, f"Recent CRITICAL data-quality issue logged: {critical_issue}"

    return False, None
