"""Data quality checks (spec section 19).

Pure functions, no I/O — operate on already-fetched bars/quotes and return
a list of QualityIssue. The caller (src/data/ingestion.py) decides what to
do with them: every issue gets persisted to data_quality_events, and any
CRITICAL issue on the most recent bar blocks that instrument from feeding
a trade decision this cycle (the "if data_bad: NO_TRADE" rule, spec
section 35) — but a lower-severity issue on old history does not retroactively
invalidate a backfill; it's logged for review instead of "silently repaired",
per spec section 19's explicit instruction never to auto-fix questionable
financial data.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum

from src.market.types import OHLCBar, Quote, Timeframe


class IssueType(str, Enum):
    MISSING_CANDLE = "MISSING_CANDLE"
    DUPLICATE_CANDLE = "DUPLICATE_CANDLE"
    TIMESTAMP_ERROR = "TIMESTAMP_ERROR"
    STALE_PRICE = "STALE_PRICE"
    ABNORMAL_SPIKE = "ABNORMAL_SPIKE"
    ZERO_PRICE = "ZERO_PRICE"
    NEGATIVE_PRICE = "NEGATIVE_PRICE"
    ABNORMAL_SPREAD = "ABNORMAL_SPREAD"
    PROVIDER_DISCREPANCY = "PROVIDER_DISCREPANCY"
    WEEKEND_ANOMALY = "WEEKEND_ANOMALY"
    TIMEZONE_ERROR = "TIMEZONE_ERROR"


class Severity(str, Enum):
    CRITICAL = "CRITICAL"  # blocks this bar/instrument from feeding a trade decision
    WARNING = "WARNING"  # logged, does not block


@dataclass
class QualityIssue:
    issue_type: IssueType
    severity: Severity
    instrument: str
    timeframe: str | None
    ts: dt.datetime
    details: dict = field(default_factory=dict)


_EXPECTED_INTERVAL = {
    Timeframe.D1: dt.timedelta(days=1),
    Timeframe.H4: dt.timedelta(hours=4),
    Timeframe.H1: dt.timedelta(hours=1),
    Timeframe.M15: dt.timedelta(minutes=15),
    Timeframe.M5: dt.timedelta(minutes=5),
}

# FX trades continuously from Sunday 22:00 UTC to Friday 22:00 UTC. Gaps
# entirely within that window are the normal weekend close, not a data
# problem — see PHASE0_REPORT.md and src/providers/oanda.py get_market_status.
_WEEKEND_CLOSE_WEEKDAY = 5  # Saturday
_FRIDAY_CLOSE_HOUR_UTC = 22
_SUNDAY_OPEN_HOUR_UTC = 22

# A single-bar move beyond this fraction of the previous close is flagged as
# a spike. 3% is deliberately generous for FX (which rarely moves this much
# intra-bar even on major news) so this catches bad ticks, not real volatility.
_SPIKE_THRESHOLD_PCT = Decimal("0.03")

# Spread wider than this fraction of mid price is flagged. Major FX pairs
# typically trade well under 0.05%; this catches broken/illiquid quotes.
_ABNORMAL_SPREAD_PCT = Decimal("0.01")

_STALE_QUOTE_THRESHOLD = dt.timedelta(minutes=5)


def _is_weekend_closed(ts: dt.datetime) -> bool:
    weekday = ts.weekday()  # Mon=0 .. Sun=6
    if weekday == _WEEKEND_CLOSE_WEEKDAY:
        return True
    if weekday == 6 and ts.hour < _SUNDAY_OPEN_HOUR_UTC:  # Sunday before open
        return True
    if weekday == 4 and ts.hour >= _FRIDAY_CLOSE_HOUR_UTC:  # Friday after close
        return True
    return False


def check_bars(instrument: str, timeframe: Timeframe, bars: list[OHLCBar]) -> list[QualityIssue]:
    """Check a batch of OHLC bars for one instrument/timeframe. Bars should
    already be sorted by ts ascending; this function sorts defensively."""
    issues: list[QualityIssue] = []
    if not bars:
        return issues

    ordered = sorted(bars, key=lambda b: b.ts)
    seen_ts: set[dt.datetime] = set()
    expected_gap = _EXPECTED_INTERVAL[timeframe]

    for i, bar in enumerate(ordered):
        # Timezone / timestamp sanity
        if bar.ts.tzinfo is None:
            issues.append(QualityIssue(
                IssueType.TIMEZONE_ERROR, Severity.CRITICAL, instrument, timeframe.value, bar.ts,
                {"reason": "timestamp is not timezone-aware"},
            ))
        elif bar.ts.utcoffset() != dt.timedelta(0):
            issues.append(QualityIssue(
                IssueType.TIMEZONE_ERROR, Severity.CRITICAL, instrument, timeframe.value, bar.ts,
                {"reason": "timestamp is not UTC", "utcoffset": str(bar.ts.utcoffset())},
            ))

        # Duplicates
        if bar.ts in seen_ts:
            issues.append(QualityIssue(
                IssueType.DUPLICATE_CANDLE, Severity.CRITICAL, instrument, timeframe.value, bar.ts, {},
            ))
        seen_ts.add(bar.ts)

        # Zero / negative prices
        for field_name in ("open", "high", "low", "close"):
            value = getattr(bar, field_name)
            if value == 0:
                issues.append(QualityIssue(
                    IssueType.ZERO_PRICE, Severity.CRITICAL, instrument, timeframe.value, bar.ts,
                    {"field": field_name},
                ))
            elif value < 0:
                issues.append(QualityIssue(
                    IssueType.NEGATIVE_PRICE, Severity.CRITICAL, instrument, timeframe.value, bar.ts,
                    {"field": field_name, "value": str(value)},
                ))

        # OHLC internal consistency (high must be >= max(open,close,low), low <= min(...))
        if bar.high < max(bar.open, bar.close, bar.low) or bar.low > min(bar.open, bar.close, bar.high):
            issues.append(QualityIssue(
                IssueType.ABNORMAL_SPIKE, Severity.CRITICAL, instrument, timeframe.value, bar.ts,
                {"reason": "OHLC values internally inconsistent (high/low don't bound open/close)"},
            ))

        # Weekend anomaly
        if instrument.count("/") == 1 and _is_weekend_closed(bar.ts):  # FX-only check
            issues.append(QualityIssue(
                IssueType.WEEKEND_ANOMALY, Severity.WARNING, instrument, timeframe.value, bar.ts,
                {"reason": "bar timestamp falls inside the normal FX weekend close"},
            ))

        # Spike vs previous close
        if i > 0:
            prev = ordered[i - 1]
            if prev.close > 0:
                move = abs(bar.close - prev.close) / prev.close
                if move > _SPIKE_THRESHOLD_PCT:
                    issues.append(QualityIssue(
                        IssueType.ABNORMAL_SPIKE, Severity.WARNING, instrument, timeframe.value, bar.ts,
                        {"move_pct": str(move), "prev_close": str(prev.close), "close": str(bar.close)},
                    ))

            # Missing candle: gap larger than expected, excluding weekend closure
            gap = bar.ts - prev.ts
            if gap > expected_gap and not (
                _is_weekend_closed(prev.ts + expected_gap) or _is_weekend_closed(bar.ts - expected_gap)
            ):
                issues.append(QualityIssue(
                    IssueType.MISSING_CANDLE, Severity.WARNING, instrument, timeframe.value, bar.ts,
                    {"gap_seconds": gap.total_seconds(), "expected_seconds": expected_gap.total_seconds()},
                ))

    return issues


def check_quote(instrument: str, quote: Quote, *, now: dt.datetime | None = None) -> list[QualityIssue]:
    """Check a single realtime quote for staleness and abnormal spread."""
    issues: list[QualityIssue] = []
    now = now or dt.datetime.now(dt.timezone.utc)

    if quote.bid <= 0 or quote.ask <= 0:
        issues.append(QualityIssue(
            IssueType.ZERO_PRICE if quote.bid == 0 or quote.ask == 0 else IssueType.NEGATIVE_PRICE,
            Severity.CRITICAL, instrument, None, quote.ts, {"bid": str(quote.bid), "ask": str(quote.ask)},
        ))
        return issues  # don't bother with spread/staleness on garbage prices

    if quote.ask < quote.bid:
        issues.append(QualityIssue(
            IssueType.ABNORMAL_SPREAD, Severity.CRITICAL, instrument, None, quote.ts,
            {"reason": "ask below bid", "bid": str(quote.bid), "ask": str(quote.ask)},
        ))
    else:
        spread_pct = quote.spread / quote.mid
        if spread_pct > _ABNORMAL_SPREAD_PCT:
            issues.append(QualityIssue(
                IssueType.ABNORMAL_SPREAD, Severity.WARNING, instrument, None, quote.ts,
                {"spread_pct": str(spread_pct)},
            ))

    if now - quote.ts > _STALE_QUOTE_THRESHOLD:
        issues.append(QualityIssue(
            IssueType.STALE_PRICE, Severity.WARNING, instrument, None, quote.ts,
            {"age_seconds": (now - quote.ts).total_seconds()},
        ))

    return issues


def check_provider_discrepancy(
    instrument: str, timeframe: Timeframe, primary: OHLCBar, secondary: OHLCBar, *, threshold_pct: Decimal = Decimal("0.005")
) -> list[QualityIssue]:
    """Compare the same bar from two providers. Not yet wired into the
    ingestion pipeline (only one live provider, OANDA, as of Phase 1) —
    provided so provider fallback (spec section 77) has a real check ready
    once a second provider is added, rather than left unimplemented."""
    issues: list[QualityIssue] = []
    if primary.close <= 0 or secondary.close <= 0:
        return issues
    diff_pct = abs(primary.close - secondary.close) / primary.close
    if diff_pct > threshold_pct:
        issues.append(QualityIssue(
            IssueType.PROVIDER_DISCREPANCY, Severity.WARNING, instrument, timeframe.value, primary.ts,
            {
                "primary_provider": primary.provider,
                "secondary_provider": secondary.provider,
                "primary_close": str(primary.close),
                "secondary_close": str(secondary.close),
                "diff_pct": str(diff_pct),
            },
        ))
    return issues


def has_blocking_issue(issues: list[QualityIssue]) -> bool:
    """The 'if data_bad: NO_TRADE' rule (spec section 35) — any CRITICAL
    issue blocks this instrument/bar from feeding a trade decision."""
    return any(issue.severity is Severity.CRITICAL for issue in issues)
