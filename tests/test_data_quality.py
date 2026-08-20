"""Tests for src/data/quality.py.

These mirror the manual verification run during development (11 scenarios,
all passed) since pytest wasn't installable in the build sandbox. Run for
real with: pip install -e ".[dev]" && pytest tests/test_data_quality.py -v
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from src.data.quality import (
    IssueType,
    check_bars,
    check_provider_discrepancy,
    check_quote,
    has_blocking_issue,
)
from src.market.types import OHLCBar, Quote, Timeframe

UTC = dt.timezone.utc


def make_bar(ts, o, h, l, c, tf=Timeframe.H1, instrument="EUR/USD", provider="oanda") -> OHLCBar:
    return OHLCBar(
        instrument=instrument, timeframe=tf, ts=ts,
        open=Decimal(str(o)), high=Decimal(str(h)), low=Decimal(str(l)), close=Decimal(str(c)),
        volume=Decimal("100"), provider=provider,
    )


@pytest.fixture
def base_ts() -> dt.datetime:
    return dt.datetime(2026, 8, 17, 0, 0, tzinfo=UTC)  # a Monday


@pytest.fixture
def clean_series(base_ts) -> list[OHLCBar]:
    return [
        make_bar(base_ts + dt.timedelta(hours=i), 1.10 + i * 0.0001, 1.1005 + i * 0.0001, 1.0995 + i * 0.0001, 1.1002 + i * 0.0001)
        for i in range(5)
    ]


def test_clean_series_has_no_issues(clean_series):
    assert check_bars("EUR/USD", Timeframe.H1, clean_series) == []


def test_zero_price_is_critical(clean_series, base_ts):
    bars = list(clean_series)
    bars[2] = make_bar(base_ts + dt.timedelta(hours=2), 0, 1.1, 1.09, 1.095)
    issues = check_bars("EUR/USD", Timeframe.H1, bars)
    assert any(i.issue_type is IssueType.ZERO_PRICE for i in issues)
    assert has_blocking_issue(issues)


def test_duplicate_candle_detected(clean_series):
    bars = clean_series + [clean_series[2]]
    issues = check_bars("EUR/USD", Timeframe.H1, bars)
    assert any(i.issue_type is IssueType.DUPLICATE_CANDLE for i in issues)


def test_missing_candle_midweek_gap(clean_series, base_ts):
    bars = [clean_series[0], clean_series[1], make_bar(base_ts + dt.timedelta(hours=5), 1.12, 1.121, 1.119, 1.120)]
    issues = check_bars("EUR/USD", Timeframe.H1, bars)
    assert any(i.issue_type is IssueType.MISSING_CANDLE for i in issues)


def test_weekend_gap_not_flagged_as_missing():
    fri = dt.datetime(2026, 8, 14, 21, 0, tzinfo=UTC)
    mon = dt.datetime(2026, 8, 17, 0, 0, tzinfo=UTC)
    bars = [make_bar(fri, 1.1, 1.101, 1.099, 1.1005), make_bar(mon, 1.1005, 1.1015, 1.0995, 1.101)]
    issues = check_bars("EUR/USD", Timeframe.H1, bars)
    assert not any(i.issue_type is IssueType.MISSING_CANDLE for i in issues)


def test_bar_actually_on_saturday_is_weekend_anomaly():
    sat = dt.datetime(2026, 8, 15, 12, 0, tzinfo=UTC)
    issues = check_bars("EUR/USD", Timeframe.H1, [make_bar(sat, 1.1, 1.101, 1.099, 1.1005)])
    assert any(i.issue_type is IssueType.WEEKEND_ANOMALY for i in issues)


def test_naive_timestamp_flagged():
    naive = make_bar(dt.datetime(2026, 8, 17, 1, 0), 1.1, 1.101, 1.099, 1.1005)
    issues = check_bars("EUR/USD", Timeframe.H1, [naive])
    assert any(i.issue_type is IssueType.TIMEZONE_ERROR for i in issues)


def test_abnormal_spike_detected(clean_series, base_ts):
    bars = [clean_series[0], clean_series[1], make_bar(base_ts + dt.timedelta(hours=2), 1.15, 1.16, 1.14, 1.155)]
    issues = check_bars("EUR/USD", Timeframe.H1, bars)
    assert any(i.issue_type is IssueType.ABNORMAL_SPIKE for i in issues)


def test_stale_quote_detected(base_ts):
    quote = Quote(instrument="EUR/USD", ts=base_ts, bid=Decimal("1.1"), ask=Decimal("1.1002"), provider="oanda")
    issues = check_quote("EUR/USD", quote, now=base_ts + dt.timedelta(minutes=10))
    assert any(i.issue_type is IssueType.STALE_PRICE for i in issues)


def test_abnormal_spread_detected(base_ts):
    quote = Quote(instrument="EUR/USD", ts=base_ts, bid=Decimal("1.10"), ask=Decimal("1.15"), provider="oanda")
    issues = check_quote("EUR/USD", quote, now=base_ts)
    assert any(i.issue_type is IssueType.ABNORMAL_SPREAD for i in issues)


def test_provider_discrepancy_detected(base_ts):
    primary = make_bar(base_ts, 1.10, 1.101, 1.099, 1.1005, provider="oanda")
    secondary = make_bar(base_ts, 1.10, 1.101, 1.099, 1.1200, provider="fmp")
    issues = check_provider_discrepancy("EUR/USD", Timeframe.H1, primary, secondary)
    assert any(i.issue_type is IssueType.PROVIDER_DISCREPANCY for i in issues)
