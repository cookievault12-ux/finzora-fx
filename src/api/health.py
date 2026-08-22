"""GET /health (spec section 94), plus the login-gated live dashboard.

Reports honestly on what Phase 1 can actually check — database and the
two Phase-1-live external services (OANDA, Telegram). Macro data, news,
LLM orchestration, live broker execution, and the scheduler process itself
aren't implemented yet (see PHASE0_REPORT.md roadmap), so this reports
them as "not_implemented" rather than faking a green check. A health
endpoint that lies about coverage is worse than one that admits gaps.

Every route in this app is now behind HTTP Basic Auth restricted to a
single hardcoded account (see src/auth/basic_auth.py) — this API is
reachable on the open internet, and per an explicit requirement, no one
else should ever be able to view it or create an account, not even by
accident.
"""

from __future__ import annotations

import datetime as dt
import os

import httpx
from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy import text

from src.api.dashboard import router as dashboard_router
from src.auth.basic_auth import require_login
from src.database.base import get_engine
from src.providers.oanda import OandaProvider
from src.telegram.client import TelegramClient

app = FastAPI(title="FINZORA FX health")
app.include_router(dashboard_router)


@app.get("/")
def root() -> RedirectResponse:
    return RedirectResponse(url="/dashboard")


def _check_database() -> dict:
    try:
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ok"}
    except Exception as exc:  # noqa: BLE001 — health check must never raise
        return {"status": "error", "detail": str(exc)}


def _check_oanda() -> dict:
    if not os.environ.get("OANDA_API_TOKEN") or not os.environ.get("OANDA_ACCOUNT_ID"):
        return {"status": "not_configured"}
    try:
        with OandaProvider() as provider:
            provider.get_instruments()
        return {"status": "ok"}
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "detail": str(exc)}


def _check_telegram() -> dict:
    if not os.environ.get("TELEGRAM_BOT_TOKEN"):
        return {"status": "not_configured"}
    try:
        client = TelegramClient()
        me = client.get_me()
        client.close()
        if not me.get("ok"):
            return {"status": "error", "detail": "getMe returned ok=false"}
        if not os.environ.get("TELEGRAM_CHAT_ID"):
            return {"status": "degraded", "detail": "bot token valid but TELEGRAM_CHAT_ID not set"}
        return {"status": "ok"}
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "detail": str(exc)}


def _check_llm(env_var: str) -> dict:
    # Deliberately does not make a live API call on every health check —
    # that would burn tokens/cost on every poll. Presence-only check.
    return {"status": "configured" if os.environ.get(env_var) else "not_configured"}


@app.get("/health")
def health(user_email: str = Depends(require_login)) -> dict:
    checks = {
        "database": _check_database(),
        "market_data": _check_oanda(),
        "macro_data": {"status": "not_implemented"},
        "news": {"status": "not_implemented"},
        "llm_primary_anthropic": _check_llm("ANTHROPIC_API_KEY"),
        "llm_secondary_nemotron": _check_llm("NEMOTRON_API_KEY"),
        "telegram": _check_telegram(),
        "broker": _check_oanda(),  # OANDA doubles as data + paper-execution provider in Phase 1
        "scheduler": {"status": "unknown", "detail": "no running-process heartbeat wired up yet"},
    }
    statuses = {c["status"] for c in checks.values()}
    if "error" in statuses:
        overall = "error"
    elif statuses & {"degraded", "not_configured", "unknown"}:
        overall = "degraded"
    else:
        overall = "ok"
    return {"status": overall, "checks": checks}


@app.get("/internal/telegram-test")
def telegram_test(token: str, user_email: str = Depends(require_login)) -> dict:
    """One-off manual smoke test: sends a real message to the configured
    Telegram chat so deployment can be confirmed end-to-end from a browser.
    Gated by INTERNAL_ADMIN_TOKEN (set on Railway, never committed) so this
    can't be triggered by anyone who just guesses the URL path."""
    expected = os.environ.get("INTERNAL_ADMIN_TOKEN")
    if not expected or token != expected:
        raise HTTPException(status_code=403, detail="forbidden")
    try:
        client = TelegramClient()
        result = client.send_message(
            "✅ FINZORA FX — hello from Railway.\n\n"
            "Deployment is live: database, OANDA market data, and this bot "
            "are all connected. This message confirms Telegram delivery "
            "end-to-end."
        )
        client.close()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"sent": True, "telegram_response": result}


@app.get("/internal/telegram-updates")
def telegram_updates(token: str, user_email: str = Depends(require_login)) -> dict:
    """Diagnostic: raw getUpdates response, so the real chat_id for whoever
    just messaged the bot can be read off directly and compared against the
    configured TELEGRAM_CHAT_ID. Same admin-token gate as the other
    /internal endpoint."""
    expected = os.environ.get("INTERNAL_ADMIN_TOKEN")
    if not expected or token != expected:
        raise HTTPException(status_code=403, detail="forbidden")
    try:
        client = TelegramClient()
        result = client.get_updates()
        client.close()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    configured_chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    return {"configured_TELEGRAM_CHAT_ID": configured_chat_id, "telegram_response": result}


@app.get("/internal/fmp-calendar-test")
def fmp_calendar_test(token: str, user_email: str = Depends(require_login)) -> dict:
    """One-off manual check: does the already-configured free-tier
    FMP_API_KEY actually have access to the Economic Data Releases Calendar
    endpoint, or is it paid-gated? Docs weren't conclusive either way (see
    Phase 3 research), so this hits the real endpoint from Railway (which
    has normal outbound network access, unlike the build sandbox) and
    reports the raw status/body back. Same admin-token gate as the other
    /internal endpoints."""
    expected = os.environ.get("INTERNAL_ADMIN_TOKEN")
    if not expected or token != expected:
        raise HTTPException(status_code=403, detail="forbidden")
    api_key = os.environ.get("FMP_API_KEY")
    if not api_key:
        return {"status": "not_configured"}
    today = dt.date.today()
    try:
        resp = httpx.get(
            "https://financialmodelingprep.com/stable/economic-calendar",
            params={
                "from": today.isoformat(),
                "to": (today + dt.timedelta(days=7)).isoformat(),
                "apikey": api_key,
            },
            timeout=15.0,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"request failed: {exc}") from exc
    body_preview = resp.text[:1500]
    return {"http_status": resp.status_code, "body_preview": body_preview}
