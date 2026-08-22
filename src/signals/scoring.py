"""Macro, geopolitical, and execution sub-scores for the signal engine
(Phase 4). Each is deliberately a simple, documented heuristic — not a
trained model — consistent with the project's rule-based-first approach
(src/features/regime.py, src/data/geopolitical_ingestion.py).

cross_asset_score and historical_setup_score are NOT computed here at all
(there's no function for them) — they stay None/not_implemented in the
stored signal, since no cross-asset data (Gold/Oil/DXY/VIX) is ingested
yet and no historical setup-outcome history exists yet. See
PHASE0_REPORT.md section 21 / the Phase 4 scoping discussion for why this
is an accepted, documented gap rather than an oversight.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.database.models.intelligence import GeopoliticalEvent
from src.database.models.market import CrossAssetData

# How stale FRED data can be before the macro backdrop is considered
# "unknown" rather than scored — FRED series are monthly/quarterly at
# best, so a wide window is correct here, not a bug.
MACRO_FRESHNESS_DAYS = 35

# Neutral baseline when the macro backdrop is present and fresh. This is
# deliberately NOT a directional (bullish/bearish USD) signal — turning a
# CPI print into a defensible directional call needs real macro modeling
# this project doesn't have yet. It's a presence/freshness check only.
MACRO_NEUTRAL_SCORE = 50.0

GEOPOLITICAL_LOOKBACK_HOURS = 24


def macro_score(session: Session) -> float | None:
    """None if we have no FRED data at all, or if the freshest row is
    older than MACRO_FRESHNESS_DAYS (macro ingestion may be failing
    silently); otherwise a flat neutral score — see module docstring."""
    latest_ts = session.scalar(select(CrossAssetData.ts).order_by(CrossAssetData.ts.desc()).limit(1))
    if latest_ts is None:
        return None
    now = dt.datetime.now(dt.timezone.utc)
    if latest_ts.tzinfo is None:
        latest_ts = latest_ts.replace(tzinfo=dt.timezone.utc)
    if (now - latest_ts).days > MACRO_FRESHNESS_DAYS:
        return None
    return MACRO_NEUTRAL_SCORE


def geopolitical_score_for_pair(session: Session, base_currency: str, quote_currency: str) -> float:
    """Inverse of the max recent geopolitical event severity affecting
    either currency in this pair: no notable recent events -> 100 (no
    dampening); a severe recent event -> a low score, meant to dampen
    confidence in a mechanical trend-continuation call, not to pick a
    direction (GDELT's severity is not directional — see
    src/data/geopolitical_ingestion.py)."""
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=GEOPOLITICAL_LOOKBACK_HOURS)
    rows = session.execute(
        select(GeopoliticalEvent.event_severity, GeopoliticalEvent.currencies_affected)
        .where(GeopoliticalEvent.ts >= cutoff)
    ).all()
    max_severity = 0.0
    for severity, currencies in rows:
        if severity is None or currencies is None:
            continue
        if base_currency in currencies or quote_currency in currencies:
            max_severity = max(max_severity, float(severity))
    return round(100.0 * (1.0 - max_severity), 2)


# Spread ceiling above which execution quality is scored 0 — a coarse,
# documented heuristic (not a learned/calibrated threshold), generous
# enough that only a genuinely bad quote (e.g. thin liquidity, a data
# glitch) triggers it for a major pair.
MAX_ACCEPTABLE_SPREAD_PIPS = 5.0


def execution_score(spread_pips: float | None) -> float | None:
    """None if no live quote was available at all (couldn't assess
    execution quality); otherwise 100 at zero spread, linearly down to 0
    at MAX_ACCEPTABLE_SPREAD_PIPS, floored at 0 beyond that."""
    if spread_pips is None:
        return None
    if spread_pips <= 0:
        return 100.0
    return round(max(0.0, 100.0 * (1.0 - spread_pips / MAX_ACCEPTABLE_SPREAD_PIPS)), 2)


def composite_score(scores: dict[str, float | None]) -> float | None:
    """Simple average of whatever sub-scores are actually available
    (mirrors src/features/regime.py's "average only available pairs"
    pattern) — None only if every single sub-score is None, since a
    composite of nothing isn't a real number."""
    available = [v for v in scores.values() if v is not None]
    if not available:
        return None
    return round(sum(available) / len(available), 2)
