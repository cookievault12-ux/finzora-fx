"""Persistence for the signal engine (Phase 4) — signals + signal_features.

Every signal snapshots exactly the feature values it was computed from
(signal_features), per spec section 63 reproducibility: a signal should be
explainable and re-derivable without needing to query live data that may
have since changed.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.database.models.market import Instrument
from src.database.models.signals import Signal, SignalFeature
from src.database.models.strategy import Strategy

STRATEGY_NAME = "FINZORA-TrendFollowing-v1"
STRATEGY_FAMILY = "TREND_FOLLOWING"
# RESEARCH, not PAPER: no backtest/walk-forward history exists yet for this
# strategy (see PHASE0_REPORT.md Phase 4 scoping) — claiming a more mature
# status than that would misrepresent how validated this actually is.
STRATEGY_STATUS = "RESEARCH"


def get_or_create_strategy(session: Session) -> int:
    existing_id = session.scalar(select(Strategy.id).where(Strategy.name == STRATEGY_NAME))
    if existing_id is not None:
        return existing_id
    strategy = Strategy(
        name=STRATEGY_NAME,
        family=STRATEGY_FAMILY,
        status=STRATEGY_STATUS,
        description=(
            "Rule-based trend-following signal generator (Phase 4 v1): ADX/MACD/SMA50-based "
            "direction, ATR-based fixed 1:2 stop/target, confirmed or vetoed by a Claude "
            "confirm/veto layer (never originates or flips direction). No backtest history "
            "yet — status is RESEARCH, not PAPER, until one exists."
        ),
        updated_at=dt.datetime.now(dt.timezone.utc),
    )
    session.add(strategy)
    session.flush()  # need the generated id before returning
    return strategy.id


def get_instrument_id(session: Session, symbol: str) -> int:
    instrument_id = session.scalar(select(Instrument.id).where(Instrument.symbol == symbol))
    if instrument_id is None:
        raise LookupError(f"Instrument {symbol!r} not found in instruments table.")
    return instrument_id


def get_last_signal(session: Session, *, instrument_symbol: str, strategy_id: int) -> tuple[int, dt.datetime] | None:
    """Returns (id, ts) of the most recent signal for this instrument+strategy,
    or None if there isn't one yet. Used to detect "no new price bar since
    last cycle" (e.g. over a weekend market closure) so the engine can skip
    re-running the full pipeline — including the paid Claude confirm/veto
    call and a duplicate Telegram alert — for data that hasn't changed."""
    instrument_id = get_instrument_id(session, instrument_symbol)
    row = session.execute(
        select(Signal.id, Signal.ts)
        .where(Signal.instrument_id == instrument_id, Signal.strategy_id == strategy_id)
        .order_by(Signal.ts.desc())
        .limit(1)
    ).first()
    return (row.id, row.ts) if row is not None else None


def store_signal(
    session: Session,
    *,
    instrument_symbol: str,
    ts: dt.datetime,
    direction: str,
    entry_price: Decimal | None,
    stop_loss: Decimal | None,
    take_profit_1: Decimal | None,
    risk_reward: Decimal | None,
    technical_score: float | None,
    macro_score: float | None,
    geopolitical_score: float | None,
    regime_score: float | None,
    execution_score: float | None,
    risk_reward_score: float | None,
    composite_score: float | None,
    final_decision: str,
    reason: str,
    llm_analysis: dict | None,
    market_regime_id: int | None,
    strategy_id: int,
    features_used: dict,
) -> int:
    """Inserts one signals row plus its signal_features snapshot. Every
    *_score field is passed through as-is, including None — a missing
    sub-score must stay visibly missing, never silently coerced to 0."""
    instrument_id = get_instrument_id(session, instrument_symbol)

    signal = Signal(
        ts=ts,
        instrument_id=instrument_id,
        direction=direction,
        entry_price=entry_price,
        execution_method="MARKET" if direction != "NO_TRADE" else None,
        stop_loss=stop_loss,
        take_profit_1=take_profit_1,
        risk_reward=risk_reward,
        technical_score=technical_score,
        macro_score=macro_score,
        geopolitical_score=geopolitical_score,
        cross_asset_score=None,  # not_implemented — no cross-asset data ingested yet
        regime_score=regime_score,
        historical_setup_score=None,  # not_implemented — no setup/outcome history exists yet
        execution_score=execution_score,
        risk_reward_score=risk_reward_score,
        composite_score=composite_score,
        p_win=None,  # not_implemented — would need calibration against real historical outcomes
        p_loss=None,
        expected_return=None,
        expected_loss=None,
        expected_value=None,
        expected_holding_period=None,
        sample_size=None,
        model_disagreement=False,  # single-LLM confirm/veto only for v1 — see PHASE0_REPORT.md section 21
        strategy_id=strategy_id,
        market_regime_id=market_regime_id,
        final_decision=final_decision,
        reason=reason,
        llm_analysis=llm_analysis,
    )
    session.add(signal)
    session.flush()  # need signal.id for the feature rows below

    for feature_name, feature_value in features_used.items():
        if feature_value is None or isinstance(feature_value, bool):
            continue  # booleans (broke_20bar_high etc.) don't fit a Numeric column
        session.add(SignalFeature(signal_id=signal.id, feature_name=feature_name, feature_value=feature_value))

    session.commit()
    return signal.id
