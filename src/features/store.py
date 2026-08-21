"""Persistence for the feature store (market_features) — spec Phase 2.

Mirrors src/data/ingestion.py's patterns: Core-level upsert (ON CONFLICT DO
UPDATE) rather than ORM session.add(), and versioned via feature_set_version
so recomputing with a new feature definition never silently overwrites or
loses the history a signal was actually generated against (spec section 63
reproducibility requirement).
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from src.database.models.market import Instrument, MarketRegime, PriceData
from src.database.models.market import MarketFeatures
from src.features.indicators import FEATURE_SET_VERSION, compute_features
from src.features.regime import METHODOLOGY_VERSION
from src.market.types import OHLCBar, Timeframe

# sma_200 needs 200 bars; pad for warmup stability on shorter EMAs/ADX too.
_LOOKBACK_BARS = 250


def get_recent_bars(
    session: Session, instrument_id: int, symbol: str, timeframe: Timeframe, limit: int = _LOOKBACK_BARS
) -> list[OHLCBar]:
    """Fetches the most recent `limit` bars for one instrument/timeframe
    from price_data, returned oldest-first (as compute_features expects)."""
    rows = session.execute(
        select(PriceData)
        .where(PriceData.instrument_id == instrument_id, PriceData.timeframe == timeframe.value)
        .order_by(PriceData.ts.desc())
        .limit(limit)
    ).scalars().all()
    rows = list(reversed(rows))
    return [
        OHLCBar(
            instrument=symbol, timeframe=timeframe, ts=row.ts,
            open=row.open, high=row.high, low=row.low, close=row.close,
            volume=row.volume, provider=row.provider,
        )
        for row in rows
    ]


def upsert_market_features(
    session: Session,
    instrument_id: int,
    timeframe: Timeframe,
    ts,
    features: dict,
    *,
    version: str = FEATURE_SET_VERSION,
) -> None:
    stmt = pg_insert(MarketFeatures).values(
        instrument_id=instrument_id,
        timeframe=timeframe.value,
        ts=ts,
        feature_set_version=version,
        features=features,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[
            MarketFeatures.instrument_id, MarketFeatures.timeframe,
            MarketFeatures.ts, MarketFeatures.feature_set_version,
        ],
        set_={"features": stmt.excluded.features},
    )
    session.execute(stmt)


def get_instrument_id(session: Session, symbol: str) -> int:
    instrument_id = session.scalar(select(Instrument.id).where(Instrument.symbol == symbol))
    if instrument_id is None:
        raise LookupError(f"Instrument {symbol!r} not found in instruments table.")
    return instrument_id


def compute_and_store_features(
    session: Session, symbol: str, timeframe: Timeframe
) -> dict | None:
    """Fetches recent price_data for one instrument/timeframe, computes the
    Phase 2 feature vector for the latest bar, and upserts it. Returns the
    computed feature dict, or None if there's no price_data yet at all
    (nothing to compute against — not an error, just nothing ingested yet)."""
    instrument_id = get_instrument_id(session, symbol)
    bars = get_recent_bars(session, instrument_id, symbol, timeframe)
    if not bars:
        return None
    features = compute_features(bars)
    upsert_market_features(session, instrument_id, timeframe, bars[-1].ts, features)
    session.commit()
    return features


def store_market_regime(
    session: Session, ts, labels: list[str], confidence: float | None, *, version: str = METHODOLOGY_VERSION
) -> None:
    """Inserts one market_regimes row. Unlike market_features, this table
    has no unique constraint to upsert against (spec's DDL treats each
    classification run as its own historical snapshot, not something later
    runs overwrite) — so a fresh regime classification each cycle is simply
    a new row, which is what the regime_labels JSONB audit trail is for."""
    confidence_decimal = Decimal(str(round(confidence, 4))) if confidence is not None else None
    session.add(MarketRegime(ts=ts, regime_labels=labels, confidence=confidence_decimal, methodology_version=version))
    session.commit()
