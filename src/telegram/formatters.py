"""Telegram message formatters — one function per template in spec
sections 57 (signal), 58 (no-trade scan), 60 (daily report), 61 (weekly
report). Every formatter takes a small dataclass, not loose kwargs, so the
shape of what a caller must supply is explicit and typed.

These build plain text (no Telegram HTML entities needed — the templates
are already visually structured with box-drawing characters and emoji);
send with parse_mode left at the client's default.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal

_DIVIDER = "━━━━━━━━━━━━━━━━━━━━"


@dataclass
class SignalMessage:
    pair: str
    direction: str  # LONG | SHORT
    status: str  # e.g. 'PAPER TRADE'
    entry: Decimal
    stop_loss: Decimal
    take_profit_1: Decimal
    take_profit_2: Decimal | None
    risk_reward: Decimal
    signal_score: int  # 0-100
    model_confidence: int  # 0-100 (percent)
    expected_holding: str  # e.g. '3-7 days'
    similar_setups: int
    historical_win_rate: Decimal  # percent
    average_return: Decimal  # percent
    median_return: Decimal  # percent
    max_adverse_excursion: Decimal  # percent
    fed_summary: str
    ecb_summary: str
    yield_differential_summary: str
    geopolitical_risk: str  # e.g. 'MODERATE'
    geopolitical_impact: str
    dxy_summary: str
    gold_summary: str
    vix_summary: str
    us2y_summary: str
    why_this_trade: list[str]
    model_version: str
    ts_sgt: dt.datetime
    is_paper: bool = True


def format_signal(m: SignalMessage) -> str:
    tp2_line = f"\n\nTAKE PROFIT 2\n{m.take_profit_2}" if m.take_profit_2 is not None else ""
    why = "\n".join(f"• {line}" for line in m.why_this_trade)
    return (
        f"{_DIVIDER}\n"
        f"🚨 FINZORA FX SIGNAL\n"
        f"{_DIVIDER}\n\n"
        f"PAIR\n{m.pair}\n\n"
        f"DIRECTION\n{m.direction}\n\n"
        f"STATUS\n📝 {m.status}\n\n"
        f"ENTRY\n{m.entry}\n\n"
        f"STOP LOSS\n{m.stop_loss}\n\n"
        f"TAKE PROFIT 1\n{m.take_profit_1}"
        f"{tp2_line}\n\n"
        f"RISK / REWARD\n{m.risk_reward}\n\n"
        f"SIGNAL SCORE\n{m.signal_score} / 100\n\n"
        f"MODEL CONFIDENCE\n{m.model_confidence}%\n\n"
        f"EXPECTED HOLDING\n{m.expected_holding}\n\n"
        f"{_DIVIDER}\n"
        f"📊 5-YEAR HISTORICAL CONTEXT\n"
        f"{_DIVIDER}\n\n"
        f"Similar setups:\n{m.similar_setups}\n\n"
        f"Historical win rate:\n{m.historical_win_rate}%\n\n"
        f"Average return:\n{m.average_return}%\n\n"
        f"Median return:\n{m.median_return}%\n\n"
        f"Max adverse excursion:\n{m.max_adverse_excursion}%\n\n"
        f"{_DIVIDER}\n"
        f"🌍 MACRO\n"
        f"{_DIVIDER}\n\n"
        f"Fed:\n{m.fed_summary}\n\n"
        f"ECB:\n{m.ecb_summary}\n\n"
        f"Yield differential:\n{m.yield_differential_summary}\n\n"
        f"{_DIVIDER}\n"
        f"🌐 GEOPOLITICAL\n"
        f"{_DIVIDER}\n\n"
        f"Risk:\n{m.geopolitical_risk}\n\n"
        f"Impact:\n{m.geopolitical_impact}\n\n"
        f"{_DIVIDER}\n"
        f"📈 CROSS-ASSET\n"
        f"{_DIVIDER}\n\n"
        f"DXY:\n{m.dxy_summary}\n\n"
        f"Gold:\n{m.gold_summary}\n\n"
        f"VIX:\n{m.vix_summary}\n\n"
        f"US 2Y:\n{m.us2y_summary}\n\n"
        f"{_DIVIDER}\n"
        f"🧠 WHY THIS TRADE\n"
        f"{_DIVIDER}\n\n"
        f"{why}\n\n"
        f"{_DIVIDER}\n\n"
        f"MODEL:\n{m.model_version}\n\n"
        f"TIME:\n{m.ts_sgt.strftime('%Y-%m-%d %H:%M')} SGT\n\n"
        f"{'⚠️ PAPER TRADE — NOT LIVE' if m.is_paper else '🔴 LIVE TRADE'}"
    )


@dataclass
class NoTradeScanMessage:
    pairs_analysed: int
    high_quality_opportunities: int
    tradeable_opportunities: int
    reason: str
    next_major_events: list[str]


def format_no_trade_scan(m: NoTradeScanMessage) -> str:
    events = "\n".join(f"• {e}" for e in m.next_major_events) if m.next_major_events else "• None scheduled"
    return (
        f"FINZORA MARKET SCAN\n\n"
        f"Pairs analysed: {m.pairs_analysed}\n\n"
        f"High-quality opportunities: {m.high_quality_opportunities}\n\n"
        f"Tradeable opportunities: {m.tradeable_opportunities}\n\n"
        f"Decision:\n\nNO TRADE\n\n"
        f"Reason:\n\n{m.reason}\n\n"
        f"Next major events:\n\n{events}"
    )


@dataclass
class DailyReportMessage:
    paper_equity: Decimal
    base_currency: str
    daily_pnl_pct: Decimal
    monthly_pct: Decimal
    ytd_pct: Decimal
    annualized_pct: Decimal
    drawdown_pct: Decimal
    open_trades: int
    currency_exposure: dict[str, Decimal]
    best_trade: str
    worst_trade: str
    current_regime: str
    geopolitical_risk: str
    major_upcoming_events: list[str]
    strategy_status: str
    system_health: str
    decision: str  # 'TRADE' | 'NO TRADE'


def format_daily_report(m: DailyReportMessage) -> str:
    exposure = "\n".join(f"{ccy}: {pct}%" for ccy, pct in m.currency_exposure.items()) or "None"
    events = "\n".join(f"• {e}" for e in m.major_upcoming_events) if m.major_upcoming_events else "• None scheduled"
    return (
        f"FINZORA DAILY REPORT\n\n"
        f"Paper Equity:\n{m.base_currency} {m.paper_equity:,.2f}\n\n"
        f"Daily P&L:\n{m.daily_pnl_pct}%\n\n"
        f"Monthly:\n{m.monthly_pct}%\n\n"
        f"YTD:\n{m.ytd_pct}%\n\n"
        f"Annualized:\n{m.annualized_pct}%\n\n"
        f"Drawdown:\n{m.drawdown_pct}%\n\n"
        f"Open Trades:\n{m.open_trades}\n\n"
        f"Currency Exposure:\n{exposure}\n\n"
        f"Best Trade:\n{m.best_trade}\n\n"
        f"Worst Trade:\n{m.worst_trade}\n\n"
        f"Current Regime:\n{m.current_regime}\n\n"
        f"Geopolitical Risk:\n{m.geopolitical_risk}\n\n"
        f"Major Upcoming Events:\n{events}\n\n"
        f"Strategy Status:\n{m.strategy_status}\n\n"
        f"System Health:\n{m.system_health}\n\n"
        f"Decision:\n{m.decision}"
    )


@dataclass
class WeeklyReportMessage:
    signals: int
    trades: int
    win_rate_pct: Decimal
    expectancy: Decimal
    profit_factor: Decimal
    sharpe: Decimal
    sortino: Decimal
    drawdown_pct: Decimal
    cagr_estimate_pct: Decimal
    pair_performance: dict[str, Decimal]  # pair -> pnl
    strategy_performance: dict[str, Decimal]  # strategy -> pnl
    regime_performance: dict[str, Decimal]  # regime -> pnl
    geopolitical_performance_note: str
    cost_analysis: str


def format_weekly_report(m: WeeklyReportMessage) -> str:
    pairs = "\n".join(f"{p}: {pnl}" for p, pnl in m.pair_performance.items()) or "None"
    strategies = "\n".join(f"{s}: {pnl}" for s, pnl in m.strategy_performance.items()) or "None"
    regimes = "\n".join(f"{r}: {pnl}" for r, pnl in m.regime_performance.items()) or "None"
    return (
        f"FINZORA WEEKLY REPORT\n\n"
        f"Signals:\n{m.signals}\n\n"
        f"Trades:\n{m.trades}\n\n"
        f"Win rate:\n{m.win_rate_pct}%\n\n"
        f"Expectancy:\n{m.expectancy}\n\n"
        f"Profit factor:\n{m.profit_factor}\n\n"
        f"Sharpe:\n{m.sharpe}\n\n"
        f"Sortino:\n{m.sortino}\n\n"
        f"Drawdown:\n{m.drawdown_pct}%\n\n"
        f"CAGR estimate:\n{m.cagr_estimate_pct}%\n\n"
        f"Pair performance:\n{pairs}\n\n"
        f"Strategy performance:\n{strategies}\n\n"
        f"Regime performance:\n{regimes}\n\n"
        f"Geopolitical performance:\n{m.geopolitical_performance_note}\n\n"
        f"Cost analysis:\n{m.cost_analysis}"
    )
