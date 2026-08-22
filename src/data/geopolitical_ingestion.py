"""GDELT -> geopolitical_events ingestion (Phase 3).

Rule-based scoring only (no LLM), consistent with the Phase 2 regime
classifier's "deterministic first" approach — every score here is a
documented, traceable function of GDELT's own fields, never an invented
number. If/when the dual-LLM signal engine is built (see
PHASE0_REPORT.md section 21 — deliberately deferred for now), an LLM could
add qualitative judgment on top of these mechanical scores, not replace
them.

Country-code -> currency mapping only covers the 8 tracked pairs' own
currencies (CAMEO 3-letter actor country codes) — a deliberate scope
limit, not an oversight: scoring events for currencies this project
doesn't even trade yet would just be noise.

NOT executed against a live GDELT file end-to-end in the build sandbox —
see src/providers/gdelt.py's module docstring. The scoring functions below
have no network/DB dependency of their own and were verified directly
against a synthetic event built to GDELT's real schema (tests/test_gdelt.py).
"""

from __future__ import annotations

import datetime as dt
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.database.models.intelligence import GeopoliticalEvent
from src.providers.gdelt import GdeltClient, GdeltEvent

logger = logging.getLogger(__name__)

# CAMEO 3-letter actor country code -> currency this project actually
# tracks. EUR is a bloc: the CAMEO "EUR" superstate code plus the largest
# Eurozone member states (covers most Eurozone-datelined news; smaller
# members are an accepted gap for v1, not an oversight).
COUNTRY_TO_CURRENCY = {
    "USA": "USD",
    "GBR": "GBP",
    "JPN": "JPY",
    "CHE": "CHF",
    "AUS": "AUD",
    "NZL": "NZD",
    "CAN": "CAD",
    "SGP": "SGD",
    "EUR": "EUR",
    "DEU": "EUR", "FRA": "EUR", "ITA": "EUR", "ESP": "EUR", "NLD": "EUR",
    "BEL": "EUR", "AUT": "EUR", "PRT": "EUR", "IRL": "EUR", "FIN": "EUR", "GRC": "EUR",
}

# CAMEO's 20 top-level "root code" event categories — a small, fixed,
# official taxonomy, used only to make the stored description readable.
CAMEO_ROOT_LABELS = {
    "01": "Make statement", "02": "Appeal", "03": "Express intent to cooperate",
    "04": "Consult", "05": "Diplomatic cooperation", "06": "Material cooperation",
    "07": "Provide aid", "08": "Yield", "09": "Investigate", "10": "Demand",
    "11": "Disapprove", "12": "Reject", "13": "Threaten", "14": "Protest",
    "15": "Exhibit force posture", "16": "Reduce relations", "17": "Coerce",
    "18": "Assault", "19": "Fight", "20": "Mass violence",
}

# Below this source count, an event is too thin/unconfirmed to be worth a
# DB row — keeps geopolitical_events from filling up with noise (same
# cost-guardrail ethos as src/monitoring/retention.py) while still catching
# anything with real cross-outlet pickup.
MIN_NUM_SOURCES = 5


def relevant_currencies(event: GdeltEvent) -> set[str]:
    currencies = set()
    for code in (event.actor1_country_code, event.actor2_country_code):
        if code in COUNTRY_TO_CURRENCY:
            currencies.add(COUNTRY_TO_CURRENCY[code])
    return currencies


def event_severity(event: GdeltEvent) -> float | None:
    """abs(GoldsteinScale) normalized from GDELT's -10..+10 range to 0..1.
    None (not 0) when GDELT itself has no Goldstein score for this event."""
    if event.goldstein_scale is None:
        return None
    return round(abs(event.goldstein_scale) / 10.0, 4)


def economic_relevance(event: GdeltEvent) -> float | None:
    """QuadClass 2/4 ('material' cooperation/conflict) events tend to carry
    more concrete economic follow-through than pure statements (QuadClass
    1/3, 'verbal'). A deliberately coarse heuristic, not a trained model —
    documented as exactly that, not a fabricated precise figure."""
    if event.quad_class is None:
        return None
    return 0.6 if event.quad_class in (2, 4) else 0.3


def confidence(event: GdeltEvent) -> float | None:
    """Saturating function of NumSources — more independent outlets
    reporting the same event means more confidence it's real and
    significant, capped at 1.0 by 20 sources."""
    if event.num_sources is None:
        return None
    return round(min(1.0, event.num_sources / 20.0), 4)


def geopolitical_score(event: GdeltEvent) -> float | None:
    sev, conf = event_severity(event), confidence(event)
    if sev is None or conf is None:
        return None
    return round(sev * conf, 4)


def build_description(event: GdeltEvent) -> str:
    root_label = CAMEO_ROOT_LABELS.get(event.event_root_code, event.event_root_code)
    parts = [f"[{root_label}] {event.actor1_name or 'UNKNOWN'} -> {event.actor2_name or 'UNKNOWN'}",
              f"(GDELT event {event.global_event_id}"]
    if event.source_url:
        parts.append(f", {event.source_url}")
    return " ".join(parts) + ")"


def get_last_gdelt_ts(session: Session) -> dt.datetime | None:
    return session.scalar(select(GeopoliticalEvent.ts).order_by(GeopoliticalEvent.ts.desc()).limit(1))


def ingest_gdelt_events(session: Session) -> dict:
    """Fetches the latest GDELT events file, filters to events involving at
    least one currency this project tracks with meaningful source pickup,
    scores them with the deterministic rules above, and inserts new rows.
    Watermarked on ts (= GDELT's DATEADDED) so re-running against the same
    file is a safe no-op rather than a duplicate insert — geopolitical_events
    has no unique constraint of its own to upsert against, so this
    application-level watermark is what prevents duplicates."""
    watermark = get_last_gdelt_ts(session)
    written = 0
    skipped_old = 0
    skipped_irrelevant = 0

    with GdeltClient() as client:
        events = client.fetch_events()

    for event in events:
        if watermark is not None and event.ts <= watermark:
            skipped_old += 1
            continue
        currencies = relevant_currencies(event)
        if not currencies or (event.num_sources or 0) < MIN_NUM_SOURCES:
            skipped_irrelevant += 1
            continue

        session.add(GeopoliticalEvent(
            event_type=event.event_root_code,
            description=build_description(event),
            countries_involved=[c for c in (event.actor1_country_code, event.actor2_country_code) if c],
            currencies_affected=sorted(currencies),
            event_severity=event_severity(event),
            currency_relevance=1.0,  # binary presence check already passed above
            economic_relevance=economic_relevance(event),
            historical_sensitivity=None,  # no historical-sensitivity model built yet — honestly absent, not guessed
            expected_duration_days=None,  # ditto
            confidence=confidence(event),
            geopolitical_score=geopolitical_score(event),
            source_count=event.num_sources or 0,
            source_quality=None,  # GDELT's events table has no source-tier info (would need the GKG/mentions tables)
            ts=event.ts,
        ))
        written += 1

    session.commit()
    return {
        "fetched": len(events),
        "written": written,
        "skipped_old": skipped_old,
        "skipped_irrelevant": skipped_irrelevant,
    }
