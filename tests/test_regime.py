"""Tests for src/features/regime.py.

Mirrors the manual verification run during development (trend+low-vol,
range+high-vol, missing-data, at-threshold scenarios — all passed
in-sandbox, pure Python/no DB dependency). Run for real with:
pip install -e ".[dev]" && pytest tests/test_regime.py -v
"""

from __future__ import annotations

from src.features.regime import (
    HIGH_VOL_RETURN_STDDEV_THRESHOLD,
    TREND_ADX_THRESHOLD,
    classify_regime,
)


def test_strong_trend_low_vol():
    features = {p: {"adx_14": 40.0, "return_stddev_20": 0.0005} for p in ("EUR/USD", "GBP/USD")}
    labels, confidence = classify_regime(features)
    assert labels == ["TRENDING", "LOW_VOLATILITY"]
    assert confidence is not None and 0.0 < confidence <= 1.0


def test_weak_trend_high_vol():
    features = {p: {"adx_14": 15.0, "return_stddev_20": 0.003} for p in ("EUR/USD", "GBP/USD")}
    labels, confidence = classify_regime(features)
    assert labels == ["RANGING", "HIGH_VOLATILITY"]


def test_no_data_returns_empty_not_a_guess():
    labels, confidence = classify_regime({"EUR/USD": {"adx_14": None, "return_stddev_20": None}})
    assert labels == []
    assert confidence is None


def test_empty_input_returns_empty():
    labels, confidence = classify_regime({})
    assert labels == []
    assert confidence is None


def test_exactly_at_thresholds_gives_zero_confidence():
    features = {"EUR/USD": {"adx_14": TREND_ADX_THRESHOLD, "return_stddev_20": HIGH_VOL_RETURN_STDDEV_THRESHOLD}}
    labels, confidence = classify_regime(features)
    assert confidence == 0.0


def test_partial_missing_data_averages_only_available_pairs():
    features = {
        "EUR/USD": {"adx_14": 40.0, "return_stddev_20": 0.0005},
        "GBP/USD": {"adx_14": None, "return_stddev_20": None},  # no feature history yet
    }
    labels, confidence = classify_regime(features)
    # should still classify off the one pair that has data, not fail
    assert labels == ["TRENDING", "LOW_VOLATILITY"]


def test_confidence_is_deterministic_and_reproducible():
    features = {"EUR/USD": {"adx_14": 35.0, "return_stddev_20": 0.002}}
    r1 = classify_regime(features)
    r2 = classify_regime(features)
    assert r1 == r2
