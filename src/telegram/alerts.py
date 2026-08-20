"""High-level alert dispatch (spec section 59).

Wires formatters.py to client.py. Each function takes the same structured
dataclass its formatter needs, formats, and sends — callers never build
Telegram strings by hand, so the template stays the single source of truth.
"""

from __future__ import annotations

from enum import Enum

from src.telegram.client import TelegramClient
from src.telegram.formatters import (
    DailyReportMessage,
    NoTradeScanMessage,
    SignalMessage,
    WeeklyReportMessage,
    format_daily_report,
    format_no_trade_scan,
    format_signal,
    format_weekly_report,
)


class AlertType(str, Enum):
    NEW_SIGNAL = "NEW_SIGNAL"
    SIGNAL_UPDATED = "SIGNAL_UPDATED"
    TRADE_OPENED = "TRADE_OPENED"
    TRADE_MODIFIED = "TRADE_MODIFIED"
    STOP_LOSS = "STOP_LOSS"
    TAKE_PROFIT = "TAKE_PROFIT"
    TRADE_CLOSED = "TRADE_CLOSED"
    DAILY_REPORT = "DAILY_REPORT"
    WEEKLY_REPORT = "WEEKLY_REPORT"
    MONTHLY_REPORT = "MONTHLY_REPORT"
    RISK_ALERT = "RISK_ALERT"
    DRAWDOWN_ALERT = "DRAWDOWN_ALERT"
    DATA_FAILURE = "DATA_FAILURE"
    MODEL_FAILURE = "MODEL_FAILURE"
    BROKER_FAILURE = "BROKER_FAILURE"
    SYSTEM_FAILURE = "SYSTEM_FAILURE"
    NO_TRADE = "NO_TRADE"


def send_signal_alert(client: TelegramClient, message: SignalMessage) -> dict:
    return client.send_message(format_signal(message))


def send_no_trade_scan(client: TelegramClient, message: NoTradeScanMessage) -> dict:
    return client.send_message(format_no_trade_scan(message))


def send_daily_report(client: TelegramClient, message: DailyReportMessage) -> dict:
    return client.send_message(format_daily_report(message))


def send_weekly_report(client: TelegramClient, message: WeeklyReportMessage) -> dict:
    return client.send_message(format_weekly_report(message))


def send_plain_alert(client: TelegramClient, alert_type: AlertType, text: str) -> dict:
    """For the simpler alert types (TRADE_OPENED, STOP_LOSS, RISK_ALERT,
    DATA_FAILURE, etc.) that don't have a dedicated multi-section template —
    prefixes with the alert type so the channel stays scannable."""
    return client.send_message(f"[{alert_type.value}]\n\n{text}")
