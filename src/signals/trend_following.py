"""Trend-following signal logic (Phase 4 v1 — the only strategy family
implemented so far, per an explicit choice to start narrow and testable
rather than building several strategies at once).

Pure functions, no I/O — mirrors src/features/regime.py's pattern of
keeping the actual decision logic deterministic, documented, and
independently testable, with any LLM synthesis layered on top in
src/signals/llm_synthesis.py rather than replacing this.

Reuses TREND_ADX_THRESHOLD from src/features/regime.py so "what counts as
trending" is defined in exactly one place, not two slightly-different
copies that could drift apart.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from src.features.regime import TREND_ADX_THRESHOLD

# ATR multiples for stop-loss / take-profit distance. Fixed, not adaptive,
# for v1 — always yields a 1:2 risk/reward by construction. A real
# optimization of these multiples needs backtest history we don't have yet
# (see historical_setup_score being explicitly not_implemented).
STOP_LOSS_ATR_MULTIPLE = 1.5
TAKE_PROFIT_ATR_MULTIPLE = 3.0

# A minimum acceptable risk/reward before a setup is worth scoring highly —
# purely a sanity floor, not a claim about optimal RR.
MIN_ACCEPTABLE_RISK_REWARD = 1.5


@dataclass
class TrendSignal:
    direction: str  # LONG | SHORT | NO_TRADE
    technical_score: float | None  # 0-100, None only when inputs are missing
    entry_price: Decimal | None
    stop_loss: Decimal | None
    take_profit_1: Decimal | None
    risk_reward: Decimal | None
    risk_reward_score: float | None
    reason: str  # short, mechanical explanation — NOT the LLM's reasoning


def compute_trend_signal(
    *, close: Decimal, features: dict, regime_labels: list[str]
) -> TrendSignal:
    """Deterministic trend-following direction + technical/risk-reward
    scoring. Never returns LONG/SHORT unless every input it needs is
    actually present — missing data means NO_TRADE, not a guess."""
    adx = features.get("adx_14")
    macd_hist = features.get("macd_histogram")
    sma_50 = features.get("sma_50")
    atr = features.get("atr_14")

    if adx is None or macd_hist is None or sma_50 is None:
        return TrendSignal(
            direction="NO_TRADE", technical_score=None, entry_price=None,
            stop_loss=None, take_profit_1=None, risk_reward=None, risk_reward_score=None,
            reason="Insufficient feature history (adx_14/macd_histogram/sma_50 not yet available).",
        )

    if "TRENDING" not in regime_labels:
        return TrendSignal(
            direction="NO_TRADE", technical_score=0.0, entry_price=None,
            stop_loss=None, take_profit_1=None, risk_reward=None, risk_reward_score=None,
            reason=f"Market-wide regime is not TRENDING ({regime_labels}) — a trend-following "
                   f"strategy shouldn't fire against its own regime.",
        )

    if adx < TREND_ADX_THRESHOLD:
        # Sub-threshold trend strength — score reflects how far short, but
        # this is never enough alone to trade.
        return TrendSignal(
            direction="NO_TRADE", technical_score=round(adx / TREND_ADX_THRESHOLD * 50, 2),
            entry_price=None, stop_loss=None, take_profit_1=None, risk_reward=None, risk_reward_score=None,
            reason=f"ADX {adx:.1f} below trend threshold {TREND_ADX_THRESHOLD}.",
        )

    close_f = float(close)
    if close_f > sma_50 and macd_hist > 0:
        direction = "LONG"
    elif close_f < sma_50 and macd_hist < 0:
        direction = "SHORT"
    else:
        # Strong ADX but price/MACD don't agree on direction — ambiguous,
        # not a coin-flip trade.
        return TrendSignal(
            direction="NO_TRADE", technical_score=round(min(adx, 100.0), 2),
            entry_price=None, stop_loss=None, take_profit_1=None, risk_reward=None, risk_reward_score=None,
            reason=f"ADX {adx:.1f} shows a strong trend, but price-vs-SMA50 and MACD histogram "
                   f"disagree on direction.",
        )

    technical_score = round(min(adx * 2, 100.0), 2)

    if atr is None or atr <= 0:
        return TrendSignal(
            direction=direction, technical_score=technical_score, entry_price=Decimal(str(close_f)),
            stop_loss=None, take_profit_1=None, risk_reward=None, risk_reward_score=None,
            reason=f"{direction} direction confirmed (ADX {adx:.1f}), but atr_14 unavailable — "
                   f"can't size a stop/target without it.",
        )

    entry = Decimal(str(close_f))
    atr_d = Decimal(str(atr))
    if direction == "LONG":
        stop_loss = entry - atr_d * Decimal(str(STOP_LOSS_ATR_MULTIPLE))
        take_profit = entry + atr_d * Decimal(str(TAKE_PROFIT_ATR_MULTIPLE))
    else:
        stop_loss = entry + atr_d * Decimal(str(STOP_LOSS_ATR_MULTIPLE))
        take_profit = entry - atr_d * Decimal(str(TAKE_PROFIT_ATR_MULTIPLE))

    risk = abs(entry - stop_loss)
    reward = abs(take_profit - entry)
    risk_reward = (reward / risk) if risk > 0 else None
    risk_reward_score = (
        round(min(float(risk_reward) / MIN_ACCEPTABLE_RISK_REWARD * 100, 100.0), 2)
        if risk_reward is not None else None
    )

    return TrendSignal(
        direction=direction,
        technical_score=technical_score,
        entry_price=entry,
        stop_loss=stop_loss,
        take_profit_1=take_profit,
        risk_reward=risk_reward,
        risk_reward_score=risk_reward_score,
        reason=f"{direction}: ADX {adx:.1f} >= {TREND_ADX_THRESHOLD} trend threshold, "
               f"price {'above' if direction == 'LONG' else 'below'} SMA50, MACD histogram "
               f"{'positive' if macd_hist > 0 else 'negative'}, regime confirms TRENDING.",
    )
