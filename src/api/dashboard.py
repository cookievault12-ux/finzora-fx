"""Server-rendered live status dashboard — the real, public-internet
version of the Cowork-only artifact, so status can be checked from any
device/browser without opening Claude. Protected by HTTP Basic Auth
restricted to a single account (src/auth/basic_auth.py).

All data is queried directly from the same Postgres this API already
connects to (no separate data layer) — a plain HTML string is built and
returned, not a templating engine, since the page is small and this avoids
adding a template-engine dependency for one page.

IMPORTANT: several fields rendered here (GDELT event descriptions, source
URLs) originate from external, untrusted content (real news articles).
Every such value is passed through html.escape() before being interpolated
into the page — skipping that would be a stored-XSS hole, since this is a
real page served over the internet, not just a local chat artifact.
"""

from __future__ import annotations

import datetime as dt
import html

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy import bindparam, text

from src.auth.basic_auth import require_login
from src.database.base import get_engine

router = APIRouter()

MAJOR_PAIRS = ["EUR/USD", "GBP/USD", "USD/JPY", "USD/CHF", "AUD/USD", "NZD/USD", "USD/CAD", "USD/SGD"]
TIMEFRAMES = ["5M", "15M", "1H", "4H", "1D"]
STORAGE_LIMIT_BYTES = 512 * 1024 * 1024  # Neon free-tier cap


def _e(value) -> str:
    """Shorthand: escape anything before it goes into the HTML string."""
    return html.escape(str(value)) if value is not None else "—"


def _fmt_ago(ts: dt.datetime | None) -> str:
    if ts is None:
        return "—"
    now = dt.datetime.now(dt.timezone.utc)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=dt.timezone.utc)
    mins = int((now - ts).total_seconds() // 60)
    if mins < 1:
        return "just now"
    if mins < 60:
        return f"{mins}m ago"
    hrs = mins // 60
    if hrs < 24:
        return f"{hrs}h ago"
    return f"{hrs // 24}d ago"


def _fmt_bytes(n: int) -> str:
    mb = n / (1024 * 1024)
    return f"{mb / 1024:.2f} GB" if mb >= 1024 else f"{mb:.1f} MB"


_STYLE = """
<style>
  :root { color-scheme: light; }
  * { box-sizing: border-box; }
  body { margin:0; padding:24px; background:#f7f7f5; color:#1a1a1a;
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif; font-size:14px; }
  h1 { font-size:20px; margin:0 0 4px 0; }
  .subtitle { color:#666; font-size:13px; margin:0 0 20px 0; }
  .grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:12px; margin-bottom:20px; }
  .card { background:#fff; border:1px solid #e5e5e0; border-radius:10px; padding:14px 16px; }
  .card .label { font-size:11px; text-transform:uppercase; letter-spacing:.04em; color:#888; margin-bottom:6px; }
  .card .value { font-size:22px; font-weight:600; }
  .card .sub { font-size:12px; color:#888; margin-top:4px; }
  .badge { display:inline-block; padding:2px 9px; border-radius:999px; font-size:12px; font-weight:600; }
  .badge.ok{background:#e3f7e8;color:#1c7c37;} .badge.warn{background:#fff3d6;color:#9a6b00;}
  .badge.err{background:#fde6e6;color:#b3261e;} .badge.unknown{background:#eee;color:#666;}
  section { background:#fff; border:1px solid #e5e5e0; border-radius:10px; padding:16px 18px; margin-bottom:16px; }
  section h2 { font-size:14px; margin:0 0 12px 0; }
  table { width:100%; border-collapse:collapse; font-size:13px; }
  th,td { text-align:left; padding:6px 8px; border-bottom:1px solid #f0f0ee; }
  th { color:#888; font-weight:500; font-size:11px; text-transform:uppercase; letter-spacing:.03em; }
  tr:last-child td { border-bottom:none; }
  .bar-track { background:#eee; border-radius:6px; height:8px; overflow:hidden; margin-top:6px; }
  .bar-fill { height:100%; background:#2f6fed; }
  .bar-fill.warn { background:#d99a00; } .bar-fill.err { background:#d9433a; }
  .muted { color:#888; }
  .topbar { display:flex; justify-content:space-between; align-items:baseline; }
</style>
"""


def _render(rows: dict, user_email: str) -> str:
    totals = rows["totals"]
    bytes_used = int(totals["bytes"] or 0)
    pct = bytes_used / STORAGE_LIMIT_BYTES

    coverage_by_pair: dict[str, dict[str, dict]] = {}
    for r in rows["coverage"]:
        coverage_by_pair.setdefault(r["symbol"], {})[r["timeframe"]] = r
    coverage_rows_html = ""
    for pair in MAJOR_PAIRS:
        cells = ""
        for tf in TIMEFRAMES:
            r = coverage_by_pair.get(pair, {}).get(tf)
            cells += (
                f"<td class='muted'>—</td>" if not r
                else f"<td>{_e(r['bars'])} <span class='muted'>({_fmt_ago(r['latest'])})</span></td>"
            )
        coverage_rows_html += f"<tr><td><strong>{_e(pair)}</strong></td>{cells}</tr>"

    regime = rows["regime"]
    if regime:
        labels = " ".join(f"<span class='badge {'warn' if ('HIGH' in l or 'TRENDING' in l) else 'ok'}'>{_e(l)}</span>" for l in (regime["regime_labels"] or []))
        regime_card = (
            "<div class='card'><div class='label'>Market Regime</div>"
            f"<div class='value'>{labels}</div>"
            f"<div class='sub'>confidence {regime['confidence']} · {_fmt_ago(regime['ts'])} · {_e(regime['methodology_version'])}</div></div>"
        )
    else:
        regime_card = (
            "<div class='card'><div class='label'>Market Regime</div>"
            "<div class='value'><span class='badge unknown'>Not yet classified</span></div></div>"
        )

    macro_rows_html = "".join(
        f"<tr><td>{_e(r['asset_symbol'])}</td><td>{_e(r['value'])}</td><td class='muted'>{_fmt_ago(r['ts'])}</td></tr>"
        for r in rows["macro"]
    ) or "<tr><td colspan='3' class='muted'>No macro data yet</td></tr>"

    yield_rows_html = "".join(
        f"<tr><td>{_e(r['country'])}</td><td>{_e(r['tenor'])}</td><td>{_e(r['yield_value'])}%</td><td class='muted'>{_fmt_ago(r['ts'])}</td></tr>"
        for r in rows["yields"]
    ) or "<tr><td colspan='4' class='muted'>No yield data yet</td></tr>"

    geo_rows_html = "".join(
        f"<tr><td class='muted'>{_fmt_ago(r['ts'])}</td><td>{_e(','.join(r['currencies_affected'] or []))}</td>"
        f"<td>{_e(r['event_severity'])}</td><td>{_e(r['geopolitical_score'])}</td>"
        f"<td>{_e(r['description'])[:140]}</td></tr>"
        for r in rows["geo"]
    ) or "<tr><td colspan='5' class='muted'>No geopolitical events yet</td></tr>"

    def _direction_badge(direction: str) -> str:
        cls = "ok" if direction == "LONG" else "err" if direction == "SHORT" else "unknown"
        return f"<span class='badge {cls}'>{_e(direction)}</span>"

    signal_rows_html = "".join(
        f"<tr><td class='muted'>{_fmt_ago(r['ts'])}</td><td>{_e(r['symbol'])}</td>"
        f"<td>{_direction_badge(r['direction'])}</td><td>{_direction_badge(r['final_decision'])}</td>"
        f"<td>{_e(r['composite_score'])}</td>"
        f"<td class='muted'>{_e(r['entry_price'])} / {_e(r['stop_loss'])} / {_e(r['take_profit_1'])}</td>"
        f"<td>{_e(r['reason'])[:160]}</td></tr>"
        for r in rows["signals"]
    ) or "<tr><td colspan='7' class='muted'>No signals generated yet</td></tr>"

    _blocked_badge = "<span class='badge err'>blocked trade</span>"
    _logged_badge = "<span class='badge warn'>logged only</span>"
    quality_rows_html = "".join(
        f"<tr><td>{_e(r['issue_type'])}</td>"
        f"<td>{_blocked_badge if r['resulted_in_no_trade'] else _logged_badge}</td>"
        f"<td>{_e(r['cnt'])}</td></tr>"
        for r in rows["quality"]
    ) or "<tr><td colspan='3' class='muted'>No data quality issues in the last 24h</td></tr>"

    error_box = "".join(
        f"{_e(r['event_type'])} ({_e(r['component'])}): <strong>{_e(r['cnt'])}</strong> in last 24h, most recent {_fmt_ago(r['latest'])}<br>"
        for r in rows["errors"]
    ) or "<span class='badge ok'>No system errors in the last 24h</span>"

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>FINZORA FX — Live Status</title>{_STYLE}</head>
<body>
  <div class="topbar">
    <div>
      <h1>FINZORA FX — Live Status</h1>
      <p class="subtitle">Signed in as {_e(user_email)} · refreshed {dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}</p>
    </div>
  </div>

  <div class="grid">
    <div class="card">
      <div class="label">DB Storage (Neon free tier)</div>
      <div class="value">{_fmt_bytes(bytes_used)}</div>
      <div class="bar-track"><div class="bar-fill {'err' if pct > 0.75 else 'warn' if pct > 0.5 else ''}" style="width:{min(pct * 100, 100):.1f}%"></div></div>
      <div class="sub">{pct * 100:.1f}% of 512 MB cap</div>
    </div>
    <div class="card">
      <div class="label">Total Price Bars</div>
      <div class="value">{_e(totals['total_price_rows'])}</div>
      <div class="sub">across {len(MAJOR_PAIRS)} tracked pairs</div>
    </div>
    <div class="card">
      <div class="label">Feature Rows</div>
      <div class="value">{_e(totals['total_feature_rows'])}</div>
      <div class="sub">feature_set_version v1</div>
    </div>
    <div class="card">
      <div class="label">Geopolitical Events</div>
      <div class="value">{_e(totals['total_geo_events'])}</div>
      <div class="sub">GDELT, rule-based scoring</div>
    </div>
    {regime_card}
  </div>

  <section>
    <h2>Live Data Coverage — 8 Major Pairs</h2>
    <table><thead><tr><th>Pair</th>{''.join(f'<th>{tf}</th>' for tf in TIMEFRAMES)}</tr></thead>
    <tbody>{coverage_rows_html}</tbody></table>
  </section>

  <section>
    <h2>Macro Indicators (FRED)</h2>
    <table><thead><tr><th>Series</th><th>Latest Value</th><th>As Of</th></tr></thead>
    <tbody>{macro_rows_html}</tbody></table>
  </section>

  <section>
    <h2>US Treasury Yields (FRED)</h2>
    <table><thead><tr><th>Country</th><th>Tenor</th><th>Yield</th><th>As Of</th></tr></thead>
    <tbody>{yield_rows_html}</tbody></table>
  </section>

  <section>
    <h2>Recent Geopolitical Events (GDELT)</h2>
    <table><thead><tr><th>When</th><th>Currencies</th><th>Severity</th><th>Score</th><th>Description</th></tr></thead>
    <tbody>{geo_rows_html}</tbody></table>
  </section>

  <section>
    <h2>Recent Signals (Phase 4 — trend-following, RESEARCH status)</h2>
    <table><thead><tr><th>When</th><th>Pair</th><th>Direction</th><th>Final Decision</th><th>Composite</th><th>Entry / Stop / Target</th><th>Reason</th></tr></thead>
    <tbody>{signal_rows_html}</tbody></table>
  </section>

  <section>
    <h2>Data Quality Events (last 24h)</h2>
    <table><thead><tr><th>Issue Type</th><th>Outcome</th><th>Count</th></tr></thead>
    <tbody>{quality_rows_html}</tbody></table>
  </section>

  <section>
    <h2>System Errors (last 24h)</h2>
    {error_box}
  </section>
</body></html>"""


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(user_email: str = Depends(require_login)) -> str:
    engine = get_engine()
    with engine.connect() as conn:
        totals = conn.execute(text("""
            SELECT
                pg_database_size(current_database()) AS bytes,
                (SELECT COUNT(*) FROM price_data) AS total_price_rows,
                (SELECT COUNT(*) FROM market_features) AS total_feature_rows,
                (SELECT COUNT(*) FROM geopolitical_events) AS total_geo_events
        """)).mappings().first()

        # bindparam(..., expanding=True) is SQLAlchemy's documented way to
        # bind a Python list into a raw text() IN-clause — safer/more
        # portable than trying to hand a list straight to Postgres's ANY(),
        # which depends on driver-level array adaptation working out of
        # the box and wasn't worth relying on unverified.
        coverage_stmt = text("""
            SELECT i.symbol, p.timeframe, COUNT(*) AS bars, MAX(p.ts) AS latest
            FROM price_data p JOIN instruments i ON i.id = p.instrument_id
            WHERE i.symbol IN :pairs
            GROUP BY i.symbol, p.timeframe ORDER BY i.symbol, p.timeframe
        """).bindparams(bindparam("pairs", expanding=True))
        coverage = conn.execute(coverage_stmt, {"pairs": MAJOR_PAIRS}).mappings().all()

        regime = conn.execute(text("""
            SELECT ts, regime_labels, confidence, methodology_version
            FROM market_regimes ORDER BY ts DESC LIMIT 1
        """)).mappings().first()

        macro = conn.execute(text("""
            SELECT DISTINCT ON (asset_symbol) asset_symbol, ts, value
            FROM cross_asset_data ORDER BY asset_symbol, ts DESC
        """)).mappings().all()

        yields_ = conn.execute(text("""
            SELECT DISTINCT ON (country, tenor) country, tenor, ts, yield_value
            FROM yield_data ORDER BY country, tenor, ts DESC
        """)).mappings().all()

        geo = conn.execute(text("""
            SELECT ts, currencies_affected, event_severity, geopolitical_score, description
            FROM geopolitical_events ORDER BY ts DESC LIMIT 10
        """)).mappings().all()

        quality = conn.execute(text("""
            SELECT issue_type, resulted_in_no_trade, COUNT(*) AS cnt
            FROM data_quality_events WHERE created_at > now() - interval '24 hours'
            GROUP BY issue_type, resulted_in_no_trade ORDER BY cnt DESC
        """)).mappings().all()

        signals = conn.execute(text("""
            SELECT s.ts, i.symbol, s.direction, s.final_decision, s.composite_score,
                   s.entry_price, s.stop_loss, s.take_profit_1, s.reason
            FROM signals s JOIN instruments i ON i.id = s.instrument_id
            ORDER BY s.ts DESC LIMIT 20
        """)).mappings().all()

        errors = conn.execute(text("""
            SELECT event_type, component, COUNT(*) AS cnt, MAX(ts) AS latest
            FROM system_events WHERE ts > now() - interval '24 hours'
            GROUP BY event_type, component ORDER BY latest DESC LIMIT 10
        """)).mappings().all()

    return _render(
        {
            "totals": totals, "coverage": coverage, "regime": regime,
            "macro": macro, "yields": yields_, "geo": geo,
            "quality": quality, "errors": errors, "signals": signals,
        },
        user_email,
    )
