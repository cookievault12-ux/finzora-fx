"""Tests for src/telegram/formatters.py — verified manually in the sandbox
(pure stdlib) before this file was written; see commit history."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

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


def _sample_signal(**overrides) -> SignalMessage:
    defaults = dict(
        pair="EUR/USD", direction="LONG", status="PAPER TRADE",
        entry=Decimal("1.1050"), stop_loss=Decimal("1.1000"),
        take_profit_1=Decimal("1.1150"), take_profit_2=Decimal("1.1200"),
        risk_reward=Decimal("2.4"), signal_score=82, model_confidence=78,
        expected_holding="3-7 days", similar_setups=423,
        historical_win_rate=Decimal("61.2"), average_return=Decimal("1.85"),
        median_return=Decimal("1.40"), max_adverse_excursion=Decimal("0.65"),
        fed_summary="On hold", ecb_summary="Cutting", yield_differential_summary="Widening",
        geopolitical_risk="MODERATE", geopolitical_impact="Limited",
        dxy_summary="Firm", gold_summary="Range", vix_summary="Low", us2y_summary="4.35%",
        why_this_trade=["A", "B"], model_version="FINZORA-v0.1",
        ts_sgt=dt.datetime(2026, 8, 19, 14, 30),
    )
    defaults.update(overrides)
    return SignalMessage(**defaults)


def test_signal_format_includes_key_fields():
    out = format_signal(_sample_signal())
    assert "FINZORA FX SIGNAL" in out
    assert "EUR/USD" in out
    assert "LONG" in out
    assert "PAPER TRADE — NOT LIVE" in out


def test_signal_format_has_blank_line_between_tp_sections():
    out = format_signal(_sample_signal())
    assert "TAKE PROFIT 1\n1.1150\n\nTAKE PROFIT 2\n1.1200" in out


def test_signal_format_omits_tp2_when_none():
    out = format_signal(_sample_signal(take_profit_2=None))
    assert "TAKE PROFIT 2" not in out


def test_signal_format_marks_live_trade_when_not_paper():
    out = format_signal(_sample_signal(is_paper=False, status="LIVE TRADE"))
    assert "🔴 LIVE TRADE" in out
    assert "PAPER TRADE — NOT LIVE" not in out


def test_no_trade_scan_format():
    msg = NoTradeScanMessage(
        pairs_analysed=20, high_quality_opportunities=0, tradeable_opportunities=0,
        reason="Current risk/reward does not justify exposure.",
        next_major_events=["FOMC Wed"],
    )
    out = format_no_trade_scan(msg)
    assert "NO TRADE" in out
    assert "FOMC Wed" in out


def test_no_trade_scan_format_handles_no_events():
    msg = NoTradeScanMessage(
        pairs_analysed=20, high_quality_opportunities=0, tradeable_opportunities=0,
        reason="No edge found.", next_major_events=[],
    )
    out = format_no_trade_scan(msg)
    assert "None scheduled" in out


def test_daily_report_format():
    msg = DailyReportMessage(
        paper_equity=Decimal("10125.50"), base_currency="SGD",
        daily_pnl_pct=Decimal("0.3"), monthly_pct=Decimal("1.2"), ytd_pct=Decimal("1.2"),
        annualized_pct=Decimal("9.8"), drawdown_pct=Decimal("2.1"), open_trades=1,
        currency_exposure={"USD": Decimal("30"), "EUR": Decimal("-30")},
        best_trade="EUR/USD +45", worst_trade="GBP/JPY -12", current_regime="TRENDING",
        geopolitical_risk="LOW", major_upcoming_events=["ECB Thu"],
        strategy_status="PAPER", system_health="OK", decision="NO TRADE",
    )
    out = format_daily_report(msg)
    assert "FINZORA DAILY REPORT" in out
    assert "SGD 10,125.50" in out
    assert "NO TRADE" in out


def test_weekly_report_format():
    msg = WeeklyReportMessage(
        signals=12, trades=3, win_rate_pct=Decimal("66.7"), expectancy=Decimal("15.2"),
        profit_factor=Decimal("1.8"), sharpe=Decimal("1.1"), sortino=Decimal("1.6"),
        drawdown_pct=Decimal("2.1"), cagr_estimate_pct=Decimal("9.8"),
        pair_performance={"EUR/USD": Decimal("45")}, strategy_performance={"trend_v0": Decimal("45")},
        regime_performance={"TRENDING": Decimal("45")},
        geopolitical_performance_note="No major events", cost_analysis="Negligible",
    )
    out = format_weekly_report(msg)
    assert "FINZORA WEEKLY REPORT" in out
    assert "EUR/USD: 45" in out
