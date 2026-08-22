"""FRED macro-series ingestion (Phase 3).

All 8 tracked pairs (EUR/USD, GBP/USD, USD/JPY, USD/CHF, AUD/USD, NZD/USD,
USD/CAD, USD/SGD) include USD, so USD-side macro data alone gives relevant
context for every pair without needing per-currency FRED series yet
(FRED's non-US coverage is thinner and less reliably free of publication
lag than its US series). Non-USD central bank data is a later addition,
likely alongside src/data/quality.py-style provider-specific handling once
we know which currencies actually need it for a live signal.

Persists into two existing tables (already in migrations/sql/0001_initial_schema.sql,
built ahead of Phase 3):
  - cross_asset_data: single-value macro series (CPI, unemployment, Fed
    funds rate, real GDP) — asset_symbol is a plain string key, not tied
    to a tradeable instrument.
  - yield_data: US Treasury yields (2Y/5Y/10Y), which already have a
    dedicated table with (country, tenor, ts, source) uniqueness.

Ingestion is upsert-based (ON CONFLICT DO UPDATE) so re-running never
duplicates a row, and so a later revision to an already-published FRED
print (which does happen — e.g. an initial estimate revised a month
later) correctly overwrites the old value rather than adding a second row.

NOT executed in the build sandbox (no outbound network/DB access there —
same caveat as src/data/ingestion.py). Smoke-test against the real Neon
DB + live FRED API before relying on this.
"""

from __future__ import annotations

import datetime as dt
import logging
from decimal import Decimal

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from src.database.models.intelligence import YieldData
from src.database.models.market import CrossAssetData
from src.providers.fred import FredClient

logger = logging.getLogger(__name__)

# FRED series ID -> cross_asset_data.asset_symbol
_CROSS_ASSET_SERIES = {
    "FEDFUNDS": "US_FED_FUNDS_RATE",  # monthly
    "CPIAUCSL": "US_CPI",  # monthly
    "UNRATE": "US_UNEMPLOYMENT",  # monthly
    "GDPC1": "US_REAL_GDP",  # quarterly
}

# FRED series ID -> (yield_data.country, yield_data.tenor)
_YIELD_SERIES = {
    "DGS2": ("US", "2Y"),
    "DGS5": ("US", "5Y"),
    "DGS10": ("US", "10Y"),
}

# These are monthly/quarterly/daily-at-most series, nothing like FX's 5-min
# cadence — a several-day lookback window on every run is cheap (well
# within FRED's free 120 req/min) and catches revisions to a figure that
# already published, not just brand-new prints.
_DEFAULT_LOOKBACK_DAYS = 10


def _upsert_cross_asset(
    session: Session, asset_symbol: str, ts: dt.datetime, value: Decimal | None, provider: str
) -> bool:
    if value is None:
        return False  # FRED's "." (no data yet) — never fabricate a value
    stmt = pg_insert(CrossAssetData).values(
        asset_symbol=asset_symbol, ts=ts, value=value, provider=provider,
        ingested_at=dt.datetime.now(dt.timezone.utc),
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[CrossAssetData.asset_symbol, CrossAssetData.ts, CrossAssetData.provider],
        set_={"value": stmt.excluded.value},
    )
    session.execute(stmt)
    return True


def _upsert_yield(
    session: Session, country: str, tenor: str, ts: dt.datetime, value: Decimal | None, source: str
) -> bool:
    if value is None:
        return False
    stmt = pg_insert(YieldData).values(
        country=country, tenor=tenor, ts=ts, yield_value=value, source=source,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[YieldData.country, YieldData.tenor, YieldData.ts, YieldData.source],
        set_={"yield_value": stmt.excluded.yield_value},
    )
    session.execute(stmt)
    return True


def ingest_fred_macro_data(session: Session, *, lookback_days: int = _DEFAULT_LOOKBACK_DAYS) -> dict:
    """Pulls recent observations for every tracked FRED series and upserts
    them. A single failed series (network blip, FRED-side issue) logs and
    continues rather than aborting the whole cycle — one macro series being
    unavailable shouldn't block the others, mirroring the resilience
    pattern in src/monitoring/scheduler.py's per-instrument ingestion."""
    end = dt.datetime.now(dt.timezone.utc)
    start = end - dt.timedelta(days=lookback_days)
    written = 0
    skipped_missing = 0
    failed_series: list[str] = []

    with FredClient() as client:
        for series_id, asset_symbol in _CROSS_ASSET_SERIES.items():
            try:
                observations = client.get_series_observations(series_id, start=start, end=end)
            except Exception:
                logger.exception("FRED fetch failed for series %s", series_id)
                failed_series.append(series_id)
                continue
            for obs in observations:
                if _upsert_cross_asset(session, asset_symbol, obs.date, obs.value, "fred"):
                    written += 1
                else:
                    skipped_missing += 1

        for series_id, (country, tenor) in _YIELD_SERIES.items():
            try:
                observations = client.get_series_observations(series_id, start=start, end=end)
            except Exception:
                logger.exception("FRED fetch failed for series %s", series_id)
                failed_series.append(series_id)
                continue
            for obs in observations:
                if _upsert_yield(session, country, tenor, obs.date, obs.value, "fred"):
                    written += 1
                else:
                    skipped_missing += 1

    session.commit()
    return {"written": written, "skipped_missing": skipped_missing, "failed_series": failed_series}
