"""Tests for src/signals/trend_following.py.

Mirrors the manual verification run during development (7 scenarios, all
passed in-sandbox — pytest itself isn't installable there, only
pandas/numpy/stdlib are network-reachable). Run for real with:
pip install -e ".[dev]" && pytest tests/test_trend_following.py -v
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from src.signals.trend_following import compute_trend_signal


def test_strong_uptrend_gives_long():
    features = {"adx_14": 40.0, "macd_histogram": 0.002, "sma_50": 1.1000, "atr_14": 0.0015}
    r = compute_trend_signal(close=Decimal("1.1050"), features=features, regime_labels=["TRENDING", "LOW_VOLATILITY"])
    assert r.direction == "LONG"
    assert r.technical_score == 80.0
    assert r.stop_loss < r.entry_price < r.take_profit_1
    assert r.risk_reward == pytest.approx(2.0)
    assert r.risk_reward_score == pytest.approx(100.0)


def test_strong_downtrend_gives_short():
    features = {"adx_14": 35.0, "macd_histogram": -0.002, "sma_50": 1.1000, "atr_14": 0.0015}
    r = compute_trend_signal(close=Decimal("1.0950"), features=features, regime_labels=["TRENDING", "HIGH_VOLATILITY"])
    assert r.direction == "SHORT"
    assert r.take_profit_1 < r.entry_price < r.stop_loss
    assert r.risk_reward == pytest.approx(2.0)


def test_weak_trend_below_adx_threshold_is_no_trade():
    features = {"adx_14": 15.0, "macd_histogram": 0.001, "sma_50": 1.1000, "atr_14": 0.0015}
    r = compute_trend_signal(close=Decimal("1.1010"), features=features, regime_labels=["TRENDING"])
    assert r.direction == "NO_TRADE"
    assert r.entry_price is None
    assert r.technical_score is not None and r.technical_score < 50.0


def test_regime_mismatch_forces_no_trade_even_with_strong_adx():
    features = {"adx_14": 40.0, "macd_histogram": 0.002, "sma_50": 1.1000, "atr_14": 0.0015}
    r = compute_trend_signal(close=Decimal("1.1050"), features=features, regime_labels=["RANGING", "LOW_VOLATILITY"])
    assert r.direction == "NO_TRADE"
    assert r.technical_score == 0.0


def test_ambiguous_direction_is_no_trade_not_a_guess():
    # Strong ADX but price below SMA50 while MACD histogram is positive —
    # trend/momentum disagree, so no direction should be picked.
    features = {"adx_14": 40.0, "macd_histogram": 0.002, "sma_50": 1.1000, "atr_14": 0.0015}
    r = compute_trend_signal(close=Decimal("1.0950"), features=features, regime_labels=["TRENDING"])
    assert r.direction == "NO_TRADE"


def test_missing_core_features_gives_no_trade_and_none_score():
    features = {"adx_14": None, "macd_histogram": None, "sma_50": None, "atr_14": None}
    r = compute_trend_signal(close=Decimal("1.1000"), features=features, regime_labels=["TRENDING"])
    assert r.direction == "NO_TRADE"
    assert r.technical_score is None


def test_missing_atr_confirms_direction_but_no_stop_target():
    features = {"adx_14": 40.0, "macd_histogram": 0.002, "sma_50": 1.1000, "atr_14": None}
    r = compute_trend_signal(close=Decimal("1.1050"), features=features, regime_labels=["TRENDING"])
    assert r.direction == "LONG"
    assert r.entry_price is not None
    assert r.stop_loss is None and r.take_profit_1 is None and r.risk_reward is None
