"""Data ingestion pipeline: Provider -> quality checks -> price_data.

Architecture per spec section 16:
    Provider -> Ingestion -> Validation -> Normalization -> Postgres -> Feature Store

This module is Ingestion + Validation + the Postgres write. Normalization
(UTC timestamps, symbol format) already happens at the provider boundary
(src/providers/oanda.py returns UTC-tz-aware OHLCBar with 'EUR/USD'-style
symbols), so there's nothing left to normalize here.

Every issue found by src/data/quality.py is persisted to data_quality_events
regardless of severity — nothing is silently dropped from the audit trail.
Only bars with a CRITICAL issue AT THAT BAR'S OWN TIMESTAMP are excluded
from price_data; the rest of a batch still writes even if one bar is bad,
since discarding a whole backfill over one bad candle would itself be a
data-quality problem.

NOT executed/tested end-to-end in the build sandbox: this module needs a
live Postgres connection (via DATABASE_URL) and SQLAlchemy/psycopg, neither
of which are reachable from this sandbox (see project history — pip has no
outbound network access here). The pure-logic pieces it depends on
(src/data/quality.py, src/data/rate_limit.py) were verified directly;
this orchestration layer should be smoke-tested against the real Neon
database before relying on it.
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from src.data.quality import IssueType, QualityIssue, Severity, check_bars
from src.database.models.market import Instrument, PriceData
from src.database.models.system import DataQualityEvent
from src.market.types import OHLCBar, Timeframe
from src.providers.base import MarketDataProvider

logger = logging.getLogger(__name__)


@dataclass
class IngestionResult:
    instrument: str
    timeframe: Timeframe
    bars_fetched: int
    bars_written: int
    bars_blocked: int
    issues: list[QualityIssue]

    @property
    def latest_bar_blocked(self) -> bool:
        if not self.issues:
            return False
        latest_ts = max(i.ts for i in self.issues) if self.issues else None
        return any(
            i.severity is Severity.CRITICAL and i.ts == latest_ts for i in self.issues
        )


def get_instrument_id(session: Session, symbol: str) -> int:
    instrument_id = session.scalar(select(Instrument.id).where(Instrument.symbol == symbol))
    if instrument_id is None:
        raise LookupError(
            f"Instrument {symbol!r} not found — seed it in migrations/sql/0002_seed_fx_universe.sql "
            "(or its equivalent for a new instrument) before ingesting data for it."
        )
    return instrument_id


def get_last_ingested_ts(
    session: Session, instrument_id: int, timeframe: Timeframe, provider: str
) -> dt.datetime | None:
    return session.scalar(
        select(PriceData.ts)
        .where(
            PriceData.instrument_id == instrument_id,
            PriceData.timeframe == timeframe.value,
            PriceData.provider == provider,
        )
        .order_by(PriceData.ts.desc())
        .limit(1)
    )


def _persist_issues(session: Session, instrument_id: int, issues: list[QualityIssue]) -> None:
    for issue in issues:
        session.add(
            DataQualityEvent(
                instrument_id=instrument_id,
                issue_type=issue.issue_type.value,
                timeframe=issue.timeframe,
                ts=issue.ts,
                details=issue.details,
                resulted_in_no_trade=(issue.severity is Severity.CRITICAL),
            )
        )


def _upsert_bars(session: Session, instrument_id: int, bars: list[OHLCBar]) -> int:
    if not bars:
        return 0
    rows = [
        {
            "instrument_id": instrument_id,
            "timeframe": bar.timeframe.value,
            "ts": bar.ts,
            "open": bar.open,
            "high": bar.high,
            "low": bar.low,
            "close": bar.close,
            "volume": bar.volume,
            "bid": None,
            "ask": None,
            "spread": None,
            "provider": bar.provider,
        }
        for bar in bars
    ]
    stmt = pg_insert(PriceData).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=[PriceData.instrument_id, PriceData.timeframe, PriceData.ts, PriceData.provider],
        set_={
            "open": stmt.excluded.open,
            "high": stmt.excluded.high,
            "low": stmt.excluded.low,
            "close": stmt.excluded.close,
            "volume": stmt.excluded.volume,
        },
    )
    session.execute(stmt)
    return len(rows)


def ingest_instrument_timeframe(
    session: Session,
    provider: MarketDataProvider,
    instrument_symbol: str,
    timeframe: Timeframe,
    *,
    start: dt.datetime | None = None,
    end: dt.datetime | None = None,
) -> IngestionResult:
    """Fetch bars for one instrument/timeframe, quality-check them, and
    write the non-critical ones to price_data. `start=None` means
    incremental: resume from the last stored bar for this provider."""
    instrument_id = get_instrument_id(session, instrument_symbol)
    end = end or dt.datetime.now(dt.timezone.utc)

    if start is None:
        last_ts = get_last_ingested_ts(session, instrument_id, timeframe, provider.name)
        start = (last_ts + dt.timedelta(seconds=1)) if last_ts else (end - dt.timedelta(days=30))

    bars = provider.get_historical_prices(instrument_symbol, timeframe, start, end)
    issues = check_bars(instrument_symbol, timeframe, bars)
    _persist_issues(session, instrument_id, issues)

    critical_ts = {i.ts for i in issues if i.severity is Severity.CRITICAL}
    good_bars = [b for b in bars if b.ts not in critical_ts]
    written = _upsert_bars(session, instrument_id, good_bars)
    session.commit()

    result = IngestionResult(
        instrument=instrument_symbol,
        timeframe=timeframe,
        bars_fetched=len(bars),
        bars_written=written,
        bars_blocked=len(bars) - len(good_bars),
        issues=issues,
    )
    if result.bars_blocked:
        logger.warning(
            "%s %s: %d/%d bars blocked by data quality (%s)",
            instrument_symbol, timeframe.value, result.bars_blocked, result.bars_fetched,
            {i.issue_type.value for i in issues if i.severity is Severity.CRITICAL},
        )
    return result


def backfill_instrument(
    session: Session,
    provider: MarketDataProvider,
    instrument_symbol: str,
    timeframe: Timeframe,
    years: int,
    *,
    chunk_days: int = 365,
) -> list[IngestionResult]:
    """Backfill `years` of history in `chunk_days`-sized windows, so a
    failure partway through only loses one chunk's progress, not the whole
    backfill, and so OANDA's 5000-candle-per-request cap (already paginated
    inside OandaProvider) never has to satisfy a multi-year request in one
    call."""
    end = dt.datetime.now(dt.timezone.utc)
    start = end - dt.timedelta(days=365 * years)
    results = []
    cursor = start
    while cursor < end:
        chunk_end = min(cursor + dt.timedelta(days=chunk_days), end)
        results.append(
            ingest_instrument_timeframe(
                session, provider, instrument_symbol, timeframe, start=cursor, end=chunk_end
            )
        )
        cursor = chunk_end
    return results
