"""Tests for the "no new H1 bar since last cycle" skip logic added to
src/signals/engine.py (22 Aug 2026) — discovered live in production over
a weekend market closure: OANDA's latest H1 candle stops advancing while
the FX market is shut, but the scheduler kept firing hourly, re-running
the full pipeline (including a paid Claude confirm/veto call and a
Telegram alert) 11 times in a row for EUR/USD alone against the exact
same stale bar.

The fix mirrors the exact conditional now in generate_signal_for_instrument:
    last = get_last_signal(session, instrument_symbol=..., strategy_id=...)
    if last is not None and last[1] == ts:
        return last[0]  # skip: no new information since last cycle

This is isolated here as pure logic since the full function can't be
exercised in the build sandbox (SQLAlchemy/anthropic/httpx aren't
installable — no network egress). get_last_signal()'s SQL query itself
(ORDER BY ts DESC LIMIT 1, scoped to instrument+strategy) was reviewed by
inspection instead, same as other DB-dependent helpers in this project
(e.g. src/signals/gate.py, src/signals/scoring.py). Run the real
integration for real with:
pip install -e ".[dev]" && pytest tests/test_signal_dedup.py -v
"""

from __future__ import annotations

import datetime as dt


def _should_skip(last: tuple[int, dt.datetime] | None, new_bar_ts: dt.datetime) -> bool:
    """Exact mirror of the conditional in generate_signal_for_instrument."""
    return last is not None and last[1] == new_bar_ts


def test_skips_when_last_signal_ts_matches_new_bar_ts():
    stale_bar_ts = dt.datetime(2026, 8, 21, 20, 0, tzinfo=dt.timezone.utc)
    last = (42, stale_bar_ts)
    assert _should_skip(last, stale_bar_ts) is True


def test_does_not_skip_when_new_bar_ts_is_newer():
    old_bar_ts = dt.datetime(2026, 8, 21, 20, 0, tzinfo=dt.timezone.utc)
    new_bar_ts = dt.datetime(2026, 8, 24, 21, 0, tzinfo=dt.timezone.utc)  # market reopened
    last = (42, old_bar_ts)
    assert _should_skip(last, new_bar_ts) is False


def test_does_not_skip_when_no_prior_signal_exists():
    new_bar_ts = dt.datetime(2026, 8, 21, 20, 0, tzinfo=dt.timezone.utc)
    assert _should_skip(None, new_bar_ts) is False


def test_does_not_skip_on_near_miss_timestamp():
    """A one-second difference must NOT be treated as a match — only an
    exact bar-timestamp match means "genuinely the same bar." Guards
    against a future refactor loosening this to some fuzzy/rounded
    comparison that could accidentally skip a real new bar."""
    last_ts = dt.datetime(2026, 8, 22, 11, 0, 0, tzinfo=dt.timezone.utc)
    new_bar_ts = dt.datetime(2026, 8, 22, 11, 0, 1, tzinfo=dt.timezone.utc)
    last = (42, last_ts)
    assert _should_skip(last, new_bar_ts) is False
