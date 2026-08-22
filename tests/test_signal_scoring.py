"""Tests for the pure-logic parts of src/signals/scoring.py
(execution_score, composite_score — macro_score and
geopolitical_score_for_pair need a live DB session and are covered by
manual smoke-testing against Neon instead, same as other DB-dependent
modules in this project). Run for real with:
pip install -e ".[dev]" && pytest tests/test_signal_scoring.py -v
"""

from __future__ import annotations

from src.signals.scoring import composite_score, execution_score


def test_execution_score_zero_spread_is_perfect():
    assert execution_score(0) == 100.0


def test_execution_score_scales_linearly_to_ceiling():
    assert execution_score(2.5) == 50.0


def test_execution_score_floors_at_zero_beyond_ceiling():
    assert execution_score(5.0) == 0.0
    assert execution_score(10.0) == 0.0


def test_execution_score_none_when_no_quote_available():
    assert execution_score(None) is None


def test_composite_score_averages_only_available_subscores():
    assert composite_score({"a": 80.0, "b": None, "c": 20.0}) == 50.0


def test_composite_score_none_when_everything_missing():
    assert composite_score({"a": None, "b": None}) is None


def test_composite_score_single_value():
    assert composite_score({"a": 100.0}) == 100.0
