"""Cost/quota guardrails for the free-tier stack (Neon storage, mainly).

Two jobs live here, both run daily by the scheduler (src/monitoring/scheduler.py):

1. purge_stale_quality_events — data_quality_events accumulates a WARNING-level
   row for every routine, non-blocking anomaly (WEEKEND_ANOMALY on every FX
   pair's weekend gap, occasional MISSING_CANDLE/ABNORMAL_SPIKE/STALE_PRICE
   warnings). These have no long-term analytical value once reviewed and
   would otherwise grow unbounded against Neon's free-tier storage cap.
   CRITICAL issues (resulted_in_no_trade=True — the actual "if data_bad:
   NO_TRADE" audit trail required for signal reproducibility, spec section
   63) are NEVER purged by this job, regardless of age. Only the routine
   WARNING noise is subject to retention.

2. check_storage_budget — reads the live Postgres database size and warns
   over Telegram before the Neon free-tier per-branch limit (512 MiB, see
   PHASE0_REPORT.md) is reached, rather than finding out from a failed
   write.

Nothing here touches price_data (the actual OHLC history) or any other
research-value table — those are the deliverable, not the noise.
"""

from __future__ import annotations

import datetime as dt
import logging

from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from src.database.models.system import DataQualityEvent
from src.telegram.alerts import AlertType, send_plain_alert
from src.telegram.client import TelegramClient

logger = logging.getLogger(__name__)

# Routine, non-blocking data-quality noise older than this is purged.
# Configurable via env so it can be tightened/loosened without a code change.
DEFAULT_RETENTION_DAYS = 30

# Neon free-tier per-branch storage cap (see PHASE0_REPORT.md / Neon project
# settings — branch_logical_size_limit_bytes). Hardcoded rather than queried
# live since it's a plan property, not something the DB itself reports.
NEON_FREE_TIER_LIMIT_BYTES = 512 * 1024 * 1024
STORAGE_WARN_THRESHOLD_PCT = 0.75


def purge_stale_quality_events(session: Session, retention_days: int = DEFAULT_RETENTION_DAYS) -> int:
    """Delete WARNING-severity (resulted_in_no_trade=False) data_quality_events
    older than retention_days. Returns the number of rows deleted. CRITICAL
    events (resulted_in_no_trade=True) are untouched — those are the audit
    trail, not noise, and are kept indefinitely."""
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=retention_days)
    result = session.execute(
        delete(DataQualityEvent).where(
            DataQualityEvent.resulted_in_no_trade.is_(False),
            DataQualityEvent.created_at < cutoff,
        )
    )
    session.commit()
    deleted = result.rowcount or 0
    if deleted:
        logger.info("Purged %d stale (WARNING, >%dd old) data_quality_events", deleted, retention_days)
    return deleted


def get_database_size_bytes(session: Session) -> int:
    return session.scalar(select(func.pg_database_size(func.current_database())))


def check_storage_budget(
    session: Session,
    *,
    limit_bytes: int = NEON_FREE_TIER_LIMIT_BYTES,
    warn_threshold_pct: float = STORAGE_WARN_THRESHOLD_PCT,
) -> dict:
    """Checks current DB size against the free-tier cap and sends a Telegram
    alert once usage crosses warn_threshold_pct. Returns a small report dict
    so the caller (scheduler) can log it regardless of whether an alert fired."""
    size_bytes = get_database_size_bytes(session)
    pct = size_bytes / limit_bytes
    report = {"size_bytes": size_bytes, "limit_bytes": limit_bytes, "pct_used": pct}

    if pct >= warn_threshold_pct:
        try:
            with TelegramClient() as client:
                send_plain_alert(
                    client,
                    AlertType.SYSTEM_FAILURE,
                    (
                        f"Neon database is at {pct:.0%} of the free-tier {limit_bytes // (1024 * 1024)}MB "
                        f"storage cap ({size_bytes / (1024 * 1024):.1f}MB used).\n\n"
                        "Consider: shortening data_quality_events retention further, archiving old "
                        "price_data to cold storage, or upgrading the Neon plan."
                    ),
                )
        except Exception:  # noqa: BLE001 — never let an alert failure break the maintenance cycle
            logger.exception("Failed to send storage-budget Telegram alert")

    return report
