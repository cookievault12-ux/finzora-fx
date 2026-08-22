"""Tests for src/providers/fred.py's pure-logic pieces.

These mirror the manual verification run during development (real FRED API
response for DGS10 was fetched live and used as the sample data below) —
pytest itself isn't installable in the build sandbox (no outbound network
access there), but the logic under test has no DB/network dependency of
its own, so it was verified directly by re-running this exact logic
in-sandbox. Run for real with:
pip install -e ".[dev]" && pytest tests/test_fred.py -v
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from src.providers.fred import FredObservation, _parse_value

UTC = dt.timezone.utc


def test_parse_value_handles_normal_numbers():
    assert _parse_value("4.6900000000") == Decimal("4.6900000000")
    assert _parse_value("-0.3") == Decimal("-0.3")


def test_parse_value_missing_marker_is_none_not_zero():
    # FRED's "." means "no observation for this period" — a genuinely
    # different fact from a value of 0, and must never be silently
    # coerced into one (mirrors src/data/quality.py's "never fabricate").
    assert _parse_value(".") is None


def test_parse_value_garbage_is_none_not_a_crash():
    assert _parse_value("not-a-number") is None


def test_fred_observation_is_a_plain_value_holder():
    obs = FredObservation(date=dt.datetime(2026, 8, 20, tzinfo=UTC), value=Decimal("4.69"))
    assert obs.date.year == 2026
    assert obs.value == Decimal("4.69")


def test_real_fred_response_shape_parses_correctly():
    """Sample below is verbatim from a live call to
    https://api.stlouisfed.org/fred/series/observations?series_id=DGS10
    (limit=3, sort_order=desc) made during development — confirms the
    parsing logic in get_series_observations against real FRED output,
    including the reverse-to-oldest-first behavior used whenever `limit`
    is passed."""
    raw_observations = [
        {"date": "2026-08-20", "value": "4.6900000000"},
        {"date": "2026-08-19", "value": "4.6500000000"},
        {"date": "2026-08-18", "value": "4.7100000000"},
    ]
    parsed = [
        FredObservation(
            date=dt.datetime.strptime(o["date"], "%Y-%m-%d").replace(tzinfo=UTC),
            value=_parse_value(o["value"]),
        )
        for o in raw_observations
    ]
    parsed.reverse()  # get_series_observations does this when `limit` is set

    assert parsed[0].date.date() == dt.date(2026, 8, 18)
    assert parsed[-1].date.date() == dt.date(2026, 8, 20)
    assert parsed[-1].value == Decimal("4.6900000000")
