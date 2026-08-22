"""Tests for src/providers/gdelt.py and src/data/geopolitical_ingestion.py's
pure-logic pieces.

These mirror the manual verification run during development against a
synthetic 61-column row built to GDELT's real, published column layout
(http://data.gdeltproject.org/documentation/GDELT-Event_Codebook-V2.0.pdf) —
pytest itself isn't installable in the build sandbox (httpx has no
outbound network access to pip there), but this logic has no network/DB
dependency of its own and was verified directly. That manual pass actually
caught a real off-by-one bug (Actor2CountryCode was indexed at 18 instead
of the correct 17, which would have silently pulled Actor2KnownGroupCode
instead and broken every currency match) — fixed before this file was
written. Run for real with:
pip install -e ".[dev]" && pytest tests/test_gdelt.py -v
"""

from __future__ import annotations

import datetime as dt

import pytest

from src.data.geopolitical_ingestion import (
    COUNTRY_TO_CURRENCY,
    confidence,
    economic_relevance,
    event_severity,
    geopolitical_score,
    relevant_currencies,
)
from src.providers.gdelt import GdeltEvent, parse_event_row

UTC = dt.timezone.utc


def make_row(**overrides) -> list[str]:
    """A syntactically valid 61-column GDELT row with sensible defaults,
    overridable by column name for individual tests."""
    row = [""] * 61
    defaults = {
        0: "1234567890", 1: "20260822", 2: "202608", 3: "2026", 4: "2026.6438",
        5: "USAGOV", 6: "UNITED STATES", 7: "USA",
        15: "JPNGOV", 16: "JAPAN", 17: "JPN",
        25: "1", 26: "173", 27: "173", 28: "17",
        29: "4", 30: "-6.5", 31: "84", 32: "12", 33: "40", 34: "-4.8",
        53: "JA", 59: "20260822090000", 60: "https://example.com/article",
    }
    for idx, val in defaults.items():
        row[idx] = val
    for key, val in overrides.items():
        row[key] = val
    return row


def test_parse_event_row_extracts_correct_fields():
    event = parse_event_row(make_row())
    assert event is not None
    assert event.global_event_id == "1234567890"
    assert event.ts == dt.datetime(2026, 8, 22, 9, 0, 0, tzinfo=UTC)
    assert event.actor1_country_code == "USA"
    # column 17, not 18 — the off-by-one this test guards against regressing
    assert event.actor2_country_code == "JPN"
    assert event.event_root_code == "17"
    assert event.quad_class == 4
    assert event.goldstein_scale == -6.5
    assert event.num_sources == 12
    assert event.avg_tone == -4.8
    assert event.source_url == "https://example.com/article"


def test_parse_event_row_rejects_short_row():
    assert parse_event_row(["a", "b"]) is None


def test_parse_event_row_rejects_unparseable_date():
    assert parse_event_row(make_row(**{59: ""})) is None
    assert parse_event_row(make_row(**{59: "not-a-date"})) is None


def test_parse_event_row_blank_fields_become_none_not_empty_string():
    event = parse_event_row(make_row(**{7: "", 30: ""}))
    assert event.actor1_country_code is None
    assert event.goldstein_scale is None


def _event(**kwargs) -> GdeltEvent:
    base = dict(
        global_event_id="1", ts=dt.datetime(2026, 8, 22, tzinfo=UTC),
        actor1_name="A", actor1_country_code="USA",
        actor2_name="B", actor2_country_code="JPN",
        event_root_code="17", quad_class=4, goldstein_scale=-6.5,
        num_mentions=84, num_sources=12, num_articles=40, avg_tone=-4.8,
        action_geo_country_code="JA", source_url="https://example.com",
    )
    base.update(kwargs)
    return GdeltEvent(**base)


def test_relevant_currencies_matches_tracked_pairs_only():
    assert relevant_currencies(_event()) == {"USD", "JPY"}
    assert relevant_currencies(_event(actor1_country_code="XYZ", actor2_country_code="ABC")) == set()


def test_eur_bloc_countries_all_map_to_eur():
    for code in ("EUR", "DEU", "FRA", "ITA", "ESP"):
        assert COUNTRY_TO_CURRENCY[code] == "EUR"


def test_event_severity_normalizes_goldstein_and_handles_missing():
    assert event_severity(_event(goldstein_scale=-6.5)) == 0.65
    assert event_severity(_event(goldstein_scale=10.0)) == 1.0
    assert event_severity(_event(goldstein_scale=None)) is None


def test_economic_relevance_material_vs_verbal():
    assert economic_relevance(_event(quad_class=2)) == 0.6
    assert economic_relevance(_event(quad_class=4)) == 0.6
    assert economic_relevance(_event(quad_class=1)) == 0.3
    assert economic_relevance(_event(quad_class=3)) == 0.3
    assert economic_relevance(_event(quad_class=None)) is None


def test_confidence_saturates_at_20_sources():
    assert confidence(_event(num_sources=0)) == 0.0
    assert confidence(_event(num_sources=10)) == 0.5
    assert confidence(_event(num_sources=20)) == 1.0
    assert confidence(_event(num_sources=100)) == 1.0  # capped, not >1
    assert confidence(_event(num_sources=None)) is None


def test_geopolitical_score_is_product_of_severity_and_confidence():
    event = _event(goldstein_scale=-6.5, num_sources=12)
    assert geopolitical_score(event) == pytest.approx(0.65 * 0.6, abs=1e-4)


def test_geopolitical_score_none_when_either_input_missing():
    assert geopolitical_score(_event(goldstein_scale=None)) is None
    assert geopolitical_score(_event(num_sources=None)) is None
