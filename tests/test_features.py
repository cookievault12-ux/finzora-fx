"""Tests for src/features/indicators.py.

These mirror the manual verification run during development (monotonic
up/down trend, flat price, insufficient-history scenarios — all passed
directly in-sandbox, since pytest wasn't installable there; see project
history) since pandas/numpy ARE available in-sandbox and were actually
executed, unlike the DB-dependent modules. Run for real with:
pip install -e ".[dev]" && pytest tests/test_features.py -v
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from src.features.indicators import compute_features
from src.market.types import OHLCBar, Timeframe

UTC = dt.timezone.utc


def make_bars(prices: list[float], *, instrument="EUR/USD", tf=Timeframe.H1) -> list[OHLCBar]:
    ts0 = dt.datetime(2026, 1, 1, tzinfo=UTC)
    return [
        OHLCBar(
            instrument=instrument, timeframe=tf, ts=ts0 + dt.timedelta(hours=i),
            open=Decimal(str(p)), high=Decimal(str(p + 0.0005)), low=Decimal(str(p - 0.0005)),
            close=Decimal(str(p)), volume=Decimal("1"), provider="test",
        )
        for i, p in enumerate(prices)
    ]


def test_monotonic_uptrend_gives_max_rsi_and_strong_adx():
    prices = [1.1000 + i * 0.001 for i in range(60)]
    features = compute_features(make_bars(prices))
    assert features["rsi_14"] == 100.0
    assert features["adx_14"] > 40  # strong, unambiguous trend


def test_monotonic_downtrend_gives_min_rsi():
    prices = [1.2000 - i * 0.001 for i in range(60)]
    features = compute_features(make_bars(prices))
    assert features["rsi_14"] == 0.0


def test_flat_price_gives_stable_bands_and_no_zscore():
    features = compute_features(make_bars([1.1000] * 60))
    assert features["sma_20"] == pytest.approx(1.1000)
    assert features["bb_width_pct_20_2"] == pytest.approx(0.0)
    # zero variance -> zscore is genuinely undefined, not a fabricated 0
    assert features["zscore_20"] is None


def test_insufficient_history_returns_none_not_a_guess():
    features = compute_features(make_bars([1.10, 1.101, 1.102]))
    assert features["sma_20"] is None
    assert features["rsi_14"] is None
    assert features["adx_14"] is None
    assert features["sma_200"] is None
    # a 3-bar series still has a 1-bar return, though
    assert features["log_return_1"] is not None


def test_single_bar_does_not_raise():
    features = compute_features(make_bars([1.1000]))
    assert features["sma_20"] is None
    assert features["log_return_1"] is None


def test_empty_bars_raises():
    with pytest.raises(ValueError):
        compute_features([])


def test_swing_levels_bracket_recent_range():
    prices = [1.10] * 15 + [1.12, 1.08] + [1.10] * 3  # spike up then down within the window
    features = compute_features(make_bars(prices))
    assert features["swing_high_20"] == pytest.approx(1.12 + 0.0005)
    assert features["swing_low_20"] == pytest.approx(1.08 - 0.0005)


def test_rsi_bounded_between_0_and_100_on_noisy_series():
    import random
    random.seed(7)
    prices = [1.10]
    for _ in range(120):
        prices.append(max(0.5, prices[-1] + random.uniform(-0.002, 0.002)))
    features = compute_features(make_bars(prices))
    assert 0.0 <= features["rsi_14"] <= 100.0
    assert 0.0 <= features["stoch_k_14"] <= 100.0
    assert features["atr_14"] > 0


def test_incremental_250bar_window_matches_full_history():
    """The scheduler (src/features/store.py get_recent_bars) only ever
    fetches the last 250 bars, not the instrument's entire price_data
    history, for performance reasons. This is the Phase 2 "incremental-value
    testing" requirement: confirm that computing off a fixed rolling window
    gives the same result as computing off the full history from bar 0 —
    i.e. 250 bars is enough warmup that no indicator (including the
    exponentially-smoothed ones — EMA/RSI/ADX/ATR — which in principle
    depend on the entire series) meaningfully drifts from the "true" value.
    Without this, incremental (cycle-by-cycle) feature computation could
    silently diverge from a full recompute, which would break
    reproducibility (spec section 63)."""
    import random
    random.seed(11)
    prices = [1.1000]
    for _ in range(500):
        prices.append(max(0.5, prices[-1] + random.uniform(-0.0015, 0.0016)))
    all_bars = make_bars(prices)

    window_250 = compute_features(all_bars[-250:])
    full_history = compute_features(all_bars)

    for key, full_value in full_history.items():
        windowed_value = window_250[key]
        if full_value is None or isinstance(full_value, bool):
            assert windowed_value == full_value, f"{key}: {windowed_value!r} != {full_value!r}"
            continue
        rel_diff = abs(windowed_value - full_value) / (abs(full_value) + 1e-12)
        assert rel_diff < 0.01, f"{key} drifted {rel_diff:.4%} between 250-bar window and full history"
