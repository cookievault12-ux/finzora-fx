"""Scheduled jobs for data ingestion + feature/regime computation (spec
section 79, Phase 1 + Phase 2 + Phase 3 macro).

Pipeline per cycle, per spec section 16 (Provider -> Ingestion ->
Validation -> Normalization -> Postgres -> Feature Store): ingest bars for
an instrument/timeframe, then immediately compute and store its Phase 2
feature vector from whatever is now in price_data. On the H1 cycle only,
also aggregate that cycle's features across the 8 major pairs into a
market-wide regime classification (src/features/regime.py).

Phase 3 macro data (FRED) runs on its own once-daily cadence, separate from
the FX ingestion loops above — it's monthly/quarterly-granularity data, so
polling it every 5 minutes would be pure waste. FMP economic calendar and
GDELT news/geopolitical ingestion aren't wired in yet (FMP free-tier access
to the calendar endpoint is still being confirmed; see
/internal/fmp-calendar-test). Signal generation and paper execution are
later phases per PHASE0_REPORT.md's roadmap and aren't implemented yet, so
scheduling them now would be scheduling jobs that don't exist.
"""

from __future__ import annotations

import datetime as dt
import logging
import os

import yaml
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.orm import Session

from src.data.ingestion import ingest_instrument_timeframe
from src.data.macro_ingestion import ingest_fred_macro_data
from src.data.rate_limit import CircuitBreaker, TokenBucket
from src.database.base import get_session_factory
from src.database.models.system import SystemEvent
from src.features.regime import classify_regime
from src.features.store import compute_and_store_features, store_market_regime
from src.market.types import Timeframe
from src.monitoring.retention import check_storage_budget, purge_stale_quality_events
from src.providers.base import MarketDataProvider
from src.providers.oanda import OandaProvider

logger = logging.getLogger(__name__)

# OANDA's documented rate limits (see PHASE0_REPORT.md broker research) are
# generous for this use case; this is a conservative default, not a
# measured ceiling.
_RATE_LIMIT = TokenBucket(capacity=10, refill_per_second=2.0)
_CIRCUIT_BREAKER = CircuitBreaker(failure_threshold=5, reset_after_seconds=120.0)

# Timeframe -> cron schedule. FX trades ~24/5, so these run every day; the
# provider layer / weekend-anomaly check handles the closed window rather
# than the scheduler trying to know market hours itself.
_SCHEDULE = {
    Timeframe.M5: CronTrigger(minute="*/5"),
    Timeframe.M15: CronTrigger(minute="*/15"),
    Timeframe.H1: CronTrigger(minute=0),
    Timeframe.H4: CronTrigger(hour="0,4,8,12,16,20", minute=0),
    Timeframe.D1: CronTrigger(hour=22, minute=5),  # shortly after the FX day rolls at 22:00 UTC
}


def _load_fx_pairs(config_path: str = "config/pairs.yaml") -> list[str]:
    """Only the 8 major pairs (config/pairs.yaml fx_pairs.majors) are
    actively ingested — these are the deepest-liquidity, most-traded pairs
    (BIS survey majors) plus USD/SGD for local relevance. The 12 cross
    pairs under fx_pairs.crosses are intentionally NOT ingested: tracking
    all 20 was overloading storage/compute for pairs with thinner volume
    and less consistent behavior than the majors. Their instrument rows and
    any already-collected price_data stay in the DB (nothing was deleted),
    they're just no longer polled going forward."""
    with open(config_path) as f:
        config = yaml.safe_load(f)
    return config["fx_pairs"]["majors"]


def _ingest_with_resilience(
    session: Session, provider: MarketDataProvider, instrument: str, timeframe: Timeframe
) -> None:
    if _CIRCUIT_BREAKER.is_open:
        logger.error("Circuit breaker open for %s — skipping %s this cycle", provider.name, instrument)
        session.add(SystemEvent(
            event_type="DATA_FAILURE", severity="ERROR", component="ingestion",
            message=f"Circuit breaker open for provider {provider.name}; skipped {instrument} {timeframe.value}",
            details={"instrument": instrument, "timeframe": timeframe.value},
            ts=dt.datetime.now(dt.timezone.utc),
        ))
        session.commit()
        return

    _RATE_LIMIT.acquire()
    try:
        result = ingest_instrument_timeframe(session, provider, instrument, timeframe)
        _CIRCUIT_BREAKER.record_success()
        if result.latest_bar_blocked:
            logger.warning("Latest bar for %s %s blocked by data quality — NO TRADE this cycle", instrument, timeframe.value)
    except Exception:
        _CIRCUIT_BREAKER.record_failure()
        logger.exception("Ingestion failed for %s %s", instrument, timeframe.value)
        session.rollback()
        session.add(SystemEvent(
            event_type="DATA_FAILURE", severity="ERROR", component="ingestion",
            message=f"Ingestion failed for {instrument} {timeframe.value}",
            details={"instrument": instrument, "timeframe": timeframe.value},
            ts=dt.datetime.now(dt.timezone.utc),
        ))
        session.commit()
        # Per spec section 93: any data outage defaults to NO NEW TRADE.
        # This function doesn't own that gate directly — the signal engine
        # (not yet built) must check for recent DATA_FAILURE system_events
        # before generating a signal for this instrument.


def _featurize_with_resilience(session: Session, instrument: str, timeframe: Timeframe) -> dict | None:
    """Runs feature computation right after ingestion for the same
    instrument/timeframe (spec section 16: Provider -> Ingestion ->
    Validation -> Normalization -> Postgres -> Feature Store, as one
    pipeline). Recomputes from whatever is currently in price_data even if
    this cycle's ingestion attempt failed — that just means the feature row
    reflects the last successfully ingested bar, which is honest, not a
    silent failure. Returns the feature dict for regime aggregation, or
    None if it couldn't be computed (no price history yet, or an error)."""
    try:
        return compute_and_store_features(session, instrument, timeframe)
    except Exception:
        logger.exception("Feature computation failed for %s %s", instrument, timeframe.value)
        session.rollback()
        session.add(SystemEvent(
            event_type="DATA_FAILURE", severity="ERROR", component="features",
            message=f"Feature computation failed for {instrument} {timeframe.value}",
            details={"instrument": instrument, "timeframe": timeframe.value},
            ts=dt.datetime.now(dt.timezone.utc),
        ))
        session.commit()
        return None


def _run_regime_classification(session: Session, features_by_pair: dict[str, dict]) -> None:
    """Aggregates this cycle's H1 features across the major pairs into a
    single market-wide regime classification (spec: market_regimes is not
    per-instrument). See src/features/regime.py for the (deliberately
    simple, explainable) rule-based methodology."""
    try:
        labels, confidence = classify_regime(features_by_pair)
        if not labels:
            logger.info("Regime classification skipped this cycle — not enough feature history yet")
            return
        store_market_regime(session, dt.datetime.now(dt.timezone.utc), labels, confidence)
        logger.info("Regime classified: %s (confidence=%s)", labels, confidence)
    except Exception:
        logger.exception("Regime classification failed")
        session.rollback()
        session.add(SystemEvent(
            event_type="DATA_FAILURE", severity="ERROR", component="regime",
            message="Regime classification cycle failed", details={},
            ts=dt.datetime.now(dt.timezone.utc),
        ))
        session.commit()


def run_ingestion_cycle(timeframe: Timeframe) -> None:
    session_factory = get_session_factory()
    provider = OandaProvider()
    pairs = _load_fx_pairs()
    features_by_pair: dict[str, dict] = {}
    try:
        with session_factory() as session:
            for instrument in pairs:
                _ingest_with_resilience(session, provider, instrument, timeframe)
                features = _featurize_with_resilience(session, instrument, timeframe)
                if features is not None:
                    features_by_pair[instrument] = features

            # Regime is classified off H1 only — a stable enough timeframe
            # for "is the market trending/volatile right now" without
            # reclassifying every 5 minutes off noisier M5 data.
            if timeframe is Timeframe.H1:
                _run_regime_classification(session, features_by_pair)
    finally:
        provider.close()


def run_maintenance_cycle() -> None:
    """Daily cost/quota guardrail: purge stale WARNING-level data-quality
    noise and warn over Telegram before the Neon free-tier storage cap is
    hit. See src/monitoring/retention.py for what is/isn't touched."""
    session_factory = get_session_factory()
    retention_days = int(os.environ.get("DATA_QUALITY_RETENTION_DAYS", "30"))
    with session_factory() as session:
        try:
            deleted = purge_stale_quality_events(session, retention_days=retention_days)
            report = check_storage_budget(session)
            logger.info(
                "Maintenance cycle: purged %d stale quality events; DB at %.1f%% of free-tier cap",
                deleted, report["pct_used"] * 100,
            )
        except Exception:
            logger.exception("Maintenance cycle failed")
            session.rollback()
            session.add(SystemEvent(
                event_type="DATA_FAILURE", severity="ERROR", component="maintenance",
                message="Daily retention/storage-budget cycle failed",
                details={}, ts=dt.datetime.now(dt.timezone.utc),
            ))
            session.commit()


def run_macro_ingestion_cycle() -> None:
    """Daily pull of US macro series (CPI, unemployment, Fed funds rate,
    real GDP, 2Y/5Y/10Y Treasury yields) from FRED. See
    src/data/macro_ingestion.py for why USD-side data alone covers all 8
    tracked pairs for now."""
    session_factory = get_session_factory()
    with session_factory() as session:
        try:
            result = ingest_fred_macro_data(session)
            logger.info(
                "Macro ingestion cycle: wrote %d observations, %d skipped (no data yet), failed series: %s",
                result["written"], result["skipped_missing"], result["failed_series"],
            )
            if result["failed_series"]:
                session.add(SystemEvent(
                    event_type="DATA_FAILURE", severity="WARNING", component="macro_ingestion",
                    message=f"FRED series failed this cycle: {result['failed_series']}",
                    details=result, ts=dt.datetime.now(dt.timezone.utc),
                ))
                session.commit()
        except Exception:
            logger.exception("Macro ingestion cycle failed")
            session.rollback()
            session.add(SystemEvent(
                event_type="DATA_FAILURE", severity="ERROR", component="macro_ingestion",
                message="Daily FRED macro ingestion cycle failed",
                details={}, ts=dt.datetime.now(dt.timezone.utc),
            ))
            session.commit()


def build_scheduler() -> BlockingScheduler:
    scheduler = BlockingScheduler(timezone="UTC")
    for timeframe, trigger in _SCHEDULE.items():
        scheduler.add_job(
            run_ingestion_cycle,
            trigger=trigger,
            args=[timeframe],
            id=f"ingest_{timeframe.value}",
            max_instances=1,
            coalesce=True,
        )
    scheduler.add_job(
        run_maintenance_cycle,
        trigger=CronTrigger(hour=23, minute=45),
        id="maintenance_retention_and_storage_budget",
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        run_macro_ingestion_cycle,
        trigger=CronTrigger(hour=1, minute=0),  # once daily, off-peak relative to the hourly FX jobs
        id="macro_ingestion_fred",
        max_instances=1,
        coalesce=True,
    )
    return scheduler


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    build_scheduler().start()
