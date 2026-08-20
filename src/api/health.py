"""GET /health (spec section 94).

Reports honestly on what Phase 1 can actually check — database and the
two Phase-1-live external services (OANDA, Telegram). Macro data, news,
LLM orchestration, live broker execution, and the scheduler process itself
aren't implemented yet (see PHASE0_REPORT.md roadmap), so this reports
them as "not_implemented" rather than faking a green check. A health
endpoint that lies about coverage is worse than one that admits gaps.
"""

from __future__ import annotations

import os

from fastapi import FastAPI
from sqlalchemy import text

from src.database.base import get_engine
from src.providers.oanda import OandaProvider
from src.telegram.client import TelegramClient

app = FastAPI(title="FINZORA FX health")


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
def health() -> dict:
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
