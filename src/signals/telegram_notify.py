"""Telegram alerts for actionable signals (Phase 4).

Only fires when final_decision is LONG or SHORT — NO_TRADE is the vast
majority of hourly cycles (8 pairs x every hour) and alerting on every one
of those would just be noise the owner would tune out. NO_TRADE decisions
are still fully recorded in `signals` and visible on the dashboard; they
just don't page anyone.

A Telegram failure (network blip, bad token) must never break signal
storage — the signal is already committed to the DB by the time this is
called, so this is purely a best-effort notification on top, wrapped so
any exception here is logged and swallowed, not raised.
"""

from __future__ import annotations

import html
import logging

from src.telegram.client import TelegramClient

logger = logging.getLogger(__name__)


def _fmt(value) -> str:
    return html.escape(str(value)) if value is not None else "—"


def format_signal_alert(
    *,
    instrument: str,
    final_decision: str,
    entry_price,
    stop_loss,
    take_profit_1,
    risk_reward,
    composite_score,
    reason: str,
) -> str:
    emoji = "🟢" if final_decision == "LONG" else "🔴"
    return (
        f"{emoji} <b>FINZORA FX — {_fmt(final_decision)} {_fmt(instrument)}</b>\n\n"
        f"Entry: {_fmt(entry_price)}\n"
        f"Stop: {_fmt(stop_loss)}\n"
        f"Target: {_fmt(take_profit_1)}\n"
        f"Risk/Reward: {_fmt(risk_reward)}\n"
        f"Composite score: {_fmt(composite_score)}/100\n\n"
        f"{_fmt(reason)}\n\n"
        f"<i>Paper research signal only (strategy status: RESEARCH, no live capital) — "
        f"not yet wired to any paper or live execution.</i>"
    )


def send_signal_alert(
    *,
    instrument: str,
    final_decision: str,
    entry_price,
    stop_loss,
    take_profit_1,
    risk_reward,
    composite_score,
    reason: str,
) -> None:
    if final_decision not in ("LONG", "SHORT"):
        return  # NO_TRADE is recorded in the DB but doesn't page anyone
    try:
        text = format_signal_alert(
            instrument=instrument, final_decision=final_decision, entry_price=entry_price,
            stop_loss=stop_loss, take_profit_1=take_profit_1, risk_reward=risk_reward,
            composite_score=composite_score, reason=reason,
        )
        client = TelegramClient()
        client.send_message(text)
        client.close()
    except Exception:  # noqa: BLE001 — a notification failure must never break signal storage
        logger.exception("Failed to send Telegram alert for %s signal", instrument)
