"""Signal engine orchestrator (Phase 4) — ties together features, regime,
scoring, the NO_TRADE data-quality gate, and the Claude confirm/veto layer
into stored `signals` rows. Runs once per instrument on the H1 cycle,
right after regime classification (src/monitoring/scheduler.py), since
market_regimes is a single global row per cycle, not per-instrument.

Every call writes a signals row — including NO_TRADE ones — since a NO_TRADE
decision with its reasoning is itself part of the audit trail, not a
no-op to skip logging. The one exception: if the underlying H1 price bar
hasn't advanced since the last cycle (e.g. a weekend market closure), the
call is a genuine no-op — it returns the existing row's id without
re-running scoring, the Claude confirm/veto call, or sending another
Telegram alert, since none of those would reflect any new information.
"""

from __future__ import annotations

import datetime as dt
import logging

from sqlalchemy.orm import Session

from src.features.store import get_recent_bars
from src.llm.claude_client import confirm_or_veto
from src.market.types import Timeframe
from src.providers.oanda import OandaProvider
from src.signals.gate import has_recent_data_failure
from src.signals.scoring import composite_score, execution_score, geopolitical_score_for_pair, macro_score
from src.signals.store import get_instrument_id, get_last_signal, get_or_create_strategy, store_signal
from src.signals.telegram_notify import send_signal_alert
from src.signals.trend_following import compute_trend_signal

logger = logging.getLogger(__name__)

_SIGNAL_TIMEFRAME = Timeframe.H1


def _split_pair(symbol: str) -> tuple[str, str]:
    base, quote = symbol.split("/")
    return base, quote


def _empty_no_trade(
    session: Session, *, instrument_symbol: str, reason: str, features_used: dict,
    market_regime_id: int | None, strategy_id: int,
) -> int:
    return store_signal(
        session, instrument_symbol=instrument_symbol, ts=dt.datetime.now(dt.timezone.utc),
        direction="NO_TRADE", entry_price=None, stop_loss=None, take_profit_1=None, risk_reward=None,
        technical_score=None, macro_score=None, geopolitical_score=None, regime_score=None,
        execution_score=None, risk_reward_score=None, composite_score=None,
        final_decision="NO_TRADE", reason=reason, llm_analysis=None,
        market_regime_id=market_regime_id, strategy_id=strategy_id, features_used=features_used,
    )


def generate_signal_for_instrument(
    session: Session,
    provider: OandaProvider,
    instrument_symbol: str,
    *,
    features: dict,
    regime_labels: list[str],
    regime_confidence: float | None,
    market_regime_id: int | None,
) -> int:
    """Generates and stores one signal for `instrument_symbol`, returning
    the new signal's id. Always writes a row, even for NO_TRADE."""
    strategy_id = get_or_create_strategy(session)

    blocked, block_reason = has_recent_data_failure(session, instrument_symbol)
    if blocked:
        return _empty_no_trade(
            session, instrument_symbol=instrument_symbol,
            reason=f"Data-quality gate: {block_reason}", features_used={},
            market_regime_id=market_regime_id, strategy_id=strategy_id,
        )

    instrument_id = get_instrument_id(session, instrument_symbol)
    bars = get_recent_bars(session, instrument_id, instrument_symbol, _SIGNAL_TIMEFRAME, limit=1)
    if not bars:
        return _empty_no_trade(
            session, instrument_symbol=instrument_symbol,
            reason="No recent H1 price bar available.", features_used=features,
            market_regime_id=market_regime_id, strategy_id=strategy_id,
        )
    close = bars[-1].close
    ts = bars[-1].ts

    # No new closed H1 bar since the last cycle (e.g. weekend market
    # closure, or a provider hiccup) — re-running the full pipeline would
    # burn a paid Claude confirm/veto call and, since NO_TRADE now alerts
    # too, send a duplicate Telegram message for data that hasn't changed.
    # Skip entirely and return the existing row.
    last = get_last_signal(session, instrument_symbol=instrument_symbol, strategy_id=strategy_id)
    if last is not None and last[1] == ts:
        logger.info(
            "No new H1 bar for %s since last signal (ts=%s) — skipping regeneration.",
            instrument_symbol, ts,
        )
        return last[0]

    trend = compute_trend_signal(close=close, features=features, regime_labels=regime_labels)

    regime_score_value = round(regime_confidence * 100, 2) if regime_confidence is not None else None
    macro_score_value = macro_score(session)
    base, quote = _split_pair(instrument_symbol)
    geo_score_value = geopolitical_score_for_pair(session, base, quote)

    spread_pips = None
    try:
        spread = provider.get_spreads([instrument_symbol]).get(instrument_symbol)
        if spread is not None:
            # OANDA spreads come back as a raw price difference, not pips —
            # a simple pip-size heuristic (JPY pairs quote to 2 decimals,
            # everything else to 4) converts it, no calibration needed.
            pip_size = 0.01 if instrument_symbol.endswith("JPY") else 0.0001
            spread_pips = spread / pip_size
    except Exception:
        logger.exception("Could not fetch live spread for %s", instrument_symbol)
    exec_score_value = execution_score(spread_pips)

    composite = composite_score({
        "technical_score": trend.technical_score,
        "macro_score": macro_score_value,
        "geopolitical_score": geo_score_value,
        "regime_score": regime_score_value,
        "execution_score": exec_score_value,
        "risk_reward_score": trend.risk_reward_score,
    })

    final_decision = trend.direction
    reason = trend.reason
    llm_analysis = None

    if trend.direction in ("LONG", "SHORT"):
        context = {
            "instrument": instrument_symbol, "direction": trend.direction,
            "mechanical_reason": trend.reason, "entry_price": trend.entry_price,
            "stop_loss": trend.stop_loss, "take_profit_1": trend.take_profit_1,
            "risk_reward": trend.risk_reward, "technical_score": trend.technical_score,
            "regime_score": regime_score_value, "regime_labels": regime_labels,
            "regime_confidence": regime_confidence, "macro_score": macro_score_value,
            "geopolitical_score": geo_score_value, "execution_score": exec_score_value,
            "risk_reward_score": trend.risk_reward_score, "composite_score": composite,
            # Full recent-events text is deferred (would need a dedicated
            # query + truncation policy) — the geopolitical_score above
            # already reflects recent event severity numerically, so this
            # doesn't leave the LLM completely blind to it, just without
            # prose detail for v1.
            "recent_geo_events": "(see geopolitical_score above; full event text not wired in yet)",
        }
        verdict = confirm_or_veto(context)
        llm_analysis = {
            "model": "claude-haiku-4-5-20251001",
            "prompt_version": "signal-confirm-veto-v1",
            "decision": verdict.decision,
            "reasoning": verdict.reasoning,
        }
        if verdict.decision == "VETO":
            final_decision = "NO_TRADE"
            reason = f"Mechanical signal was {trend.direction}, but Claude vetoed it: {verdict.reasoning}"
        else:
            reason = f"{trend.reason} Claude confirmed: {verdict.reasoning}"

    signal_id = store_signal(
        session, instrument_symbol=instrument_symbol, ts=ts, direction=trend.direction,
        entry_price=trend.entry_price, stop_loss=trend.stop_loss, take_profit_1=trend.take_profit_1,
        risk_reward=trend.risk_reward, technical_score=trend.technical_score, macro_score=macro_score_value,
        geopolitical_score=geo_score_value, regime_score=regime_score_value, execution_score=exec_score_value,
        risk_reward_score=trend.risk_reward_score, composite_score=composite, final_decision=final_decision,
        reason=reason, llm_analysis=llm_analysis, market_regime_id=market_regime_id, strategy_id=strategy_id,
        features_used=features,
    )

    # Telegram alert for every decision, including NO_TRADE (per owner
    # request, 22 Aug 2026) — NO_TRADE gets a short one-liner with the
    # reason, LONG/SHORT get the full detailed card. Best-effort: any
    # failure here is logged inside send_signal_alert and never
    # propagates, since the signal is already safely committed to the DB
    # by this point.
    send_signal_alert(
        instrument=instrument_symbol, final_decision=final_decision,
        entry_price=trend.entry_price, stop_loss=trend.stop_loss, take_profit_1=trend.take_profit_1,
        risk_reward=trend.risk_reward, composite_score=composite, reason=reason,
    )

    return signal_id
