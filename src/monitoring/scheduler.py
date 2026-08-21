"""Scheduled jobs for data ingestion (spec section 79).

Not run/tested in the build sandbox (APScheduler isn't installable here —
no outbound package-index access; see project history). Structure and
schedule follow the spec directly; smoke-test with
`python -m src.monitoring.scheduler` once dependencies are installed and
.env is filled in.

Only market-data ingestion and a data-quality freshness sweep are wired
here — macro/news/geopolitical ingestion, feature calculation, signal
scan, and paper execution are later phases per PHASE0_REPORT.md's roadmap
and aren't implemented yet, so scheduling them now would be scheduling
jobs that don't exist.
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
from src.data.rate_limit import CircuitBreaker, TokenBucket
from src.database.base import get_session_factory
from src.database.models.system import SystemEvent
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
    with open(config_path) as f:
        config = yaml.safe_load(f)
    return config["fx_pairs"]["majors"] + config["fx_pairs"]["crosses"]


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


def run_ingestion_cycle(timeframe: Timeframe) -> None:
    session_factory = get_session_factory()
    provider = OandaProvider()
    pairs = _load_fx_pairs()
    try:
        with session_factory() as session:
            for instrument in pairs:
                _ingest_with_resilience(session, provider, instrument, timeframe)
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
    return scheduler


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    build_scheduler().start()
