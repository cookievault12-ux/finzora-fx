"""Telegram alerts for every generated signal (Phase 4).

Updated 22 Aug 2026 per owner request: originally this only fired for
LONG/SHORT (actionable) signals, to avoid ~8 msgs/hour of NO_TRADE noise.
The owner explicitly decided they'd rather see NO_TRADE too, with the
reason attached, so they can watch the system reason in near-real-time
rather than only checking the dashboard. To keep that from being pure
noise, NO_TRADE gets a short one-line message (pair + reason) while an
actionable LONG/SHORT keeps the full detailed card (entry/stop/target/
scores) — so the inbox stays scannable even at 8 messages/cycle.

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

_DECISION_EMOJI = {"LONG": "🟢", "SHORT": "🔴", "NO_TRADE": "⚪"}


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
    emoji = _DECISION_EMOJI.get(final_decision, "⚪")

    if final_decision == "NO_TRADE":
        # Short one-liner — this fires far more often than LONG/SHORT
        # (most cycles are NO_TRADE across most pairs), so it stays
        # scannable rather than repeating the full card's mostly-empty
        # entry/stop/target fields.
        return f"{emoji} <b>{_fmt(instrument)} — NO_TRADE</b>\n{_fmt(reason)}"

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
