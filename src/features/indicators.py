"""Feature engineering (spec Phase 2): trend, momentum, volatility,
statistical, and price-structure indicators computed from OHLC history.

Design principles, matching the rest of the codebase:
- Every function takes bars sorted ascending by ts and returns the feature
  value AS OF THE LAST BAR, using preceding bars as its lookback window.
- If there isn't enough history for a given indicator's window, it returns
  None rather than fabricating a value from a short/incomplete window —
  same "don't silently invent financial data" principle as src/data/quality.py.
- Uses pandas/numpy (already project dependencies) for the rolling-window
  math rather than hand-rolled loops, since Wilder's smoothing (RSI/ATR/ADX)
  is easy to get subtly wrong by hand and pandas' rolling/ewm primitives are
  well-tested.
- Pure functions, no I/O — src/features/store.py handles persistence.
"""

from __future__ import annotations

from decimal import Decimal

import numpy as np
import pandas as pd

from src.market.types import OHLCBar

FEATURE_SET_VERSION = "v1"


def _bars_to_frame(bars: list[OHLCBar]) -> pd.DataFrame:
    return pd.DataFrame({
        "open": [float(b.open) for b in bars],
        "high": [float(b.high) for b in bars],
        "low": [float(b.low) for b in bars],
        "close": [float(b.close) for b in bars],
    })


def _last_or_none(series: pd.Series, min_periods: int) -> float | None:
    """Returns the last value of a rolling/ewm series, but only once at
    least min_periods real observations have gone into it — otherwise None
    rather than an early, unstable estimate."""
    if len(series) < min_periods:
        return None
    value = series.iloc[-1]
    return None if pd.isna(value) else float(value)


# ---------------------------------------------------------------- trend ---

def sma(df: pd.DataFrame, period: int) -> float | None:
    return _last_or_none(df["close"].rolling(period).mean(), period)


def ema(df: pd.DataFrame, period: int) -> float | None:
    # A plain .ewm(span=period) never really "warms up" (it's a weighted
    # average from bar 0), so require at least `period` bars before trusting
    # it, consistent with how sma/rsi/atr all gate on window length.
    return _last_or_none(df["close"].ewm(span=period, adjust=False).mean(), period)


def macd(df: pd.DataFrame) -> tuple[float | None, float | None, float | None]:
    """Standard 12/26/9 MACD. Returns (macd, signal, histogram)."""
    if len(df) < 35:  # 26 (slow EMA) + 9 (signal EMA warmup)
        return None, None, None
    ema12 = df["close"].ewm(span=12, adjust=False).mean()
    ema26 = df["close"].ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    histogram = macd_line - signal_line
    return float(macd_line.iloc[-1]), float(signal_line.iloc[-1]), float(histogram.iloc[-1])


def adx(df: pd.DataFrame, period: int = 14) -> float | None:
    """Wilder's Average Directional Index — trend strength (not direction).
    Needs roughly 2*period bars for the smoothed +DI/-DI/DX chain to settle."""
    if len(df) < period * 2:
        return None
    high, low, close = df["high"], df["low"], df["close"]
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    prev_close = close.shift(1)
    tr = pd.concat([
        high - low, (high - prev_close).abs(), (low - prev_close).abs()
    ], axis=1).max(axis=1)

    atr_ = tr.ewm(alpha=1 / period, adjust=False).mean()
    plus_di = 100 * pd.Series(plus_dm, index=df.index).ewm(alpha=1 / period, adjust=False).mean() / atr_
    minus_di = 100 * pd.Series(minus_dm, index=df.index).ewm(alpha=1 / period, adjust=False).mean() / atr_
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
    adx_series = dx.ewm(alpha=1 / period, adjust=False).mean()
    return _last_or_none(adx_series, period * 2)


# ------------------------------------------------------------- momentum ---

def rsi(df: pd.DataFrame, period: int = 14) -> float | None:
    """Wilder's RSI."""
    if len(df) < period + 1:
        return None
    delta = df["close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi_series = 100 - (100 / (1 + rs))
    # avg_loss == 0 (straight up-run) means RSI should read 100, not NaN
    rsi_series = rsi_series.where(avg_loss != 0, 100.0)
    return _last_or_none(rsi_series, period + 1)


def stochastic(df: pd.DataFrame, k_period: int = 14, d_period: int = 3) -> tuple[float | None, float | None]:
    if len(df) < k_period + d_period:
        return None, None
    lowest_low = df["low"].rolling(k_period).min()
    highest_high = df["high"].rolling(k_period).max()
    denom = (highest_high - lowest_low).replace(0, np.nan)
    percent_k = 100 * (df["close"] - lowest_low) / denom
    percent_d = percent_k.rolling(d_period).mean()
    k = _last_or_none(percent_k, k_period)
    d = _last_or_none(percent_d, k_period + d_period)
    return k, d


def roc(df: pd.DataFrame, period: int = 10) -> float | None:
    """Rate of change: % move over `period` bars."""
    if len(df) < period + 1:
        return None
    prior = df["close"].iloc[-1 - period]
    if prior == 0:
        return None
    return float((df["close"].iloc[-1] - prior) / prior * 100)


# ------------------------------------------------------------ volatility --

def atr(df: pd.DataFrame, period: int = 14) -> float | None:
    if len(df) < period + 1:
        return None
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low, (high - prev_close).abs(), (low - prev_close).abs()
    ], axis=1).max(axis=1)
    atr_series = tr.ewm(alpha=1 / period, adjust=False).mean()
    return _last_or_none(atr_series, period + 1)


def bollinger_bands(df: pd.DataFrame, period: int = 20, num_std: float = 2.0) -> tuple[float | None, float | None, float | None]:
    """Returns (upper, lower, width_pct) where width_pct = (upper-lower)/mid*100."""
    if len(df) < period:
        return None, None, None
    mid = df["close"].rolling(period).mean()
    std = df["close"].rolling(period).std()
    upper = mid + num_std * std
    lower = mid - num_std * std
    upper_v, lower_v, mid_v = upper.iloc[-1], lower.iloc[-1], mid.iloc[-1]
    if pd.isna(upper_v) or pd.isna(lower_v) or mid_v == 0:
        return None, None, None
    width_pct = float((upper_v - lower_v) / mid_v * 100)
    return float(upper_v), float(lower_v), width_pct


def return_stddev(df: pd.DataFrame, period: int = 20) -> float | None:
    """Rolling stddev of single-bar returns. Deliberately NOT annualized —
    the annualization factor depends on the timeframe (5M vs D1 have wildly
    different bars-per-year), and mislabeling an unannualized number as
    annualized volatility would be worse than just being explicit about
    what this is: per-bar return dispersion over the last `period` bars."""
    if len(df) < period + 1:
        return None
    returns = df["close"].pct_change()
    return _last_or_none(returns.rolling(period).std(), period + 1)


# ----------------------------------------------------------- statistical --

def log_return_1(df: pd.DataFrame) -> float | None:
    if len(df) < 2 or df["close"].iloc[-2] <= 0:
        return None
    return float(np.log(df["close"].iloc[-1] / df["close"].iloc[-2]))


def return_skew(df: pd.DataFrame, period: int = 20) -> float | None:
    if len(df) < period + 1:
        return None
    returns = df["close"].pct_change()
    return _last_or_none(returns.rolling(period).skew(), period + 1)


def zscore(df: pd.DataFrame, period: int = 20) -> float | None:
    """How many rolling-stddevs the current close is from its own rolling
    mean — a normalized mean-reversion / extension signal."""
    if len(df) < period:
        return None
    mean = df["close"].rolling(period).mean()
    std = df["close"].rolling(period).std()
    if std.iloc[-1] in (0, None) or pd.isna(std.iloc[-1]):
        return None
    return float((df["close"].iloc[-1] - mean.iloc[-1]) / std.iloc[-1])


# ------------------------------------------------------- price structure -

def swing_levels(df: pd.DataFrame, period: int = 20) -> tuple[float | None, float | None, float | None, float | None]:
    """Returns (swing_high, swing_low, pct_from_high, pct_from_low) over the
    trailing `period` bars (including the current one)."""
    if len(df) < period:
        return None, None, None, None
    window_high = df["high"].iloc[-period:]
    window_low = df["low"].iloc[-period:]
    swing_high = float(window_high.max())
    swing_low = float(window_low.min())
    close = float(df["close"].iloc[-1])
    pct_from_high = (close - swing_high) / swing_high * 100 if swing_high else None
    pct_from_low = (close - swing_low) / swing_low * 100 if swing_low else None
    return swing_high, swing_low, pct_from_high, pct_from_low


def higher_high_lower_low(df: pd.DataFrame, period: int = 20) -> tuple[bool | None, bool | None]:
    """Whether the CURRENT bar's high/low broke the prior `period` bars'
    range (excluding itself) — a simple, explainable breakout flag."""
    if len(df) < period + 1:
        return None, None
    prior_high = df["high"].iloc[-period - 1:-1].max()
    prior_low = df["low"].iloc[-period - 1:-1].min()
    return bool(df["high"].iloc[-1] > prior_high), bool(df["low"].iloc[-1] < prior_low)


# --------------------------------------------------------- orchestration -

def compute_features(bars: list[OHLCBar]) -> dict:
    """Computes the full Phase 2 feature vector for the LAST bar in `bars`
    (bars must be sorted ascending by ts). Any indicator without enough
    history is set to None rather than a garbage early estimate — the
    caller (src/features/store.py) persists None as JSON null, so it's
    visible in the data that the feature genuinely wasn't computable yet,
    not silently missing."""
    if not bars:
        raise ValueError("compute_features requires at least one bar")

    df = _bars_to_frame(bars)
    macd_line, macd_signal, macd_hist = macd(df)
    stoch_k, stoch_d = stochastic(df)
    bb_upper, bb_lower, bb_width_pct = bollinger_bands(df)
    swing_high, swing_low, pct_from_high, pct_from_low = swing_levels(df)
    broke_high, broke_low = higher_high_lower_low(df)

    return {
        # trend
        "sma_20": sma(df, 20),
        "sma_50": sma(df, 50),
        "sma_200": sma(df, 200),
        "ema_12": ema(df, 12),
        "ema_26": ema(df, 26),
        "macd": macd_line,
        "macd_signal": macd_signal,
        "macd_histogram": macd_hist,
        "adx_14": adx(df, 14),
        # momentum
        "rsi_14": rsi(df, 14),
        "stoch_k_14": stoch_k,
        "stoch_d_3": stoch_d,
        "roc_10": roc(df, 10),
        # volatility
        "atr_14": atr(df, 14),
        "bb_upper_20_2": bb_upper,
        "bb_lower_20_2": bb_lower,
        "bb_width_pct_20_2": bb_width_pct,
        "return_stddev_20": return_stddev(df, 20),
        # statistical
        "log_return_1": log_return_1(df),
        "return_skew_20": return_skew(df, 20),
        "zscore_20": zscore(df, 20),
        # price structure
        "swing_high_20": swing_high,
        "swing_low_20": swing_low,
        "pct_from_swing_high_20": pct_from_high,
        "pct_from_swing_low_20": pct_from_low,
        "broke_20bar_high": broke_high,
        "broke_20bar_low": broke_low,
    }
