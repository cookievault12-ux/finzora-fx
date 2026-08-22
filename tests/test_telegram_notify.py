"""Tests for src/signals/telegram_notify.py — pure formatting logic.
Every final_decision now sends (owner request, 22 Aug 2026): NO_TRADE
gets a short one-line message, LONG/SHORT get the full detailed card.
The actual HTTP call to Telegram isn't exercised here (no network in the
build sandbox); send_signal_alert()'s try/except safety wrapper is
reviewed by inspection. Run for real with:
pip install -e ".[dev]" && pytest tests/test_telegram_notify.py -v
"""

from __future__ import annotations

from src.signals.telegram_notify import format_signal_alert


def test_long_message_has_green_emoji_and_key_fields():
    text = format_signal_alert(
        instrument="EUR/USD", final_decision="LONG", entry_price="1.0850",
        stop_loss="1.0800", take_profit_1="1.0950", risk_reward="2.0",
        composite_score=72.5, reason="Strong uptrend confirmed.",
    )
    assert "🟢" in text
    assert "LONG" in text
    assert "EUR/USD" in text
    assert "1.0850" in text
    assert "72.5" in text
    assert "RESEARCH" in text  # honesty disclaimer must always be present


def test_short_message_has_red_emoji():
    text = format_signal_alert(
        instrument="GBP/USD", final_decision="SHORT", entry_price="1.27",
        stop_loss="1.28", take_profit_1="1.25", risk_reward="2.0",
        composite_score=60.0, reason="Downtrend confirmed.",
    )
    assert "🔴" in text
    assert "SHORT" in text


def test_html_special_characters_in_reason_are_escaped():
    text = format_signal_alert(
        instrument="USD/JPY", final_decision="LONG", entry_price="150.00",
        stop_loss="149.00", take_profit_1="152.00", risk_reward="2.0",
        composite_score=55.0, reason="Trend & momentum <both> aligned",
    )
    assert "&amp;" in text
    assert "&lt;both&gt;" in text
    assert "<both>" not in text


def test_none_fields_render_as_em_dash_not_python_none():
    text = format_signal_alert(
        instrument="AUD/USD", final_decision="LONG", entry_price=None,
        stop_loss=None, take_profit_1=None, risk_reward=None,
        composite_score=None, reason="test",
    )
    assert "None" not in text
    assert "—" in text


def test_no_trade_message_is_short_one_liner_with_reason():
    text = format_signal_alert(
        instrument="GBP/USD", final_decision="NO_TRADE", entry_price=None,
        stop_loss=None, take_profit_1=None, risk_reward=None,
        composite_score=37.3, reason="ADX 21.9 below trend threshold 25.0.",
    )
    assert "⚪" in text
    assert "NO_TRADE" in text
    assert "GBP/USD" in text
    assert "ADX 21.9 below trend threshold 25.0." in text
    # NO_TRADE fires far more often than LONG/SHORT — it must stay a
    # one-liner, not repeat the full card's mostly-empty fields.
    assert "Entry:" not in text
    assert "RESEARCH" not in text


def test_no_trade_reason_is_html_escaped_too():
    text = format_signal_alert(
        instrument="USD/CHF", final_decision="NO_TRADE", entry_price=None,
        stop_loss=None, take_profit_1=None, risk_reward=None,
        composite_score=None, reason="A & B <disagree>",
    )
    assert "&amp;" in text
    assert "&lt;disagree&gt;" in text
    assert "<disagree>" not in text
