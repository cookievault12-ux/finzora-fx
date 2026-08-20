"""Thin Telegram Bot API client (spec section 56).

Uses httpx directly against the Bot API rather than a full bot framework —
FINZORA only ever posts to one channel, it doesn't need to handle inbound
commands, so a framework would be unnecessary weight (spec section 82).

TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID are read from the environment only.
Never hardcoded, never logged, never printed, never sent to an LLM (spec
section 56) — note in particular that the bot API base URL itself embeds
the token, so this module is careful never to log `self._base_url` or any
exception that might include it; only the response body/status is logged.
"""

from __future__ import annotations

import logging
import os

import httpx

logger = logging.getLogger(__name__)


class TelegramClient:
    def __init__(self, bot_token: str | None = None, chat_id: str | None = None):
        self._token = bot_token or os.environ.get("TELEGRAM_BOT_TOKEN")
        self._chat_id = chat_id or os.environ.get("TELEGRAM_CHAT_ID")
        if not self._token:
            raise RuntimeError("TELEGRAM_BOT_TOKEN is not set (see .env.example).")
        self._base_url = f"https://api.telegram.org/bot{self._token}"
        self._client = httpx.Client(timeout=15.0)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "TelegramClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def send_message(self, text: str, *, chat_id: str | None = None, parse_mode: str = "HTML") -> dict:
        target = chat_id or self._chat_id
        if not target:
            raise RuntimeError(
                "No chat_id configured. Set TELEGRAM_CHAT_ID in .env, or run "
                "get_chat_id_from_updates() once after posting a message in "
                "the channel with the bot added as admin."
            )
        try:
            resp = self._client.post(
                f"{self._base_url}/sendMessage",
                json={
                    "chat_id": target,
                    "text": text,
                    "parse_mode": parse_mode,
                    "disable_web_page_preview": True,
                },
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            # Log the Telegram API's error body (no secrets in it) without
            # ever logging the request URL, which embeds the bot token.
            logger.error("Telegram sendMessage failed: %s", exc.response.text)
            raise
        return resp.json()

    def get_updates(self) -> dict:
        """One-time helper for discovering TELEGRAM_CHAT_ID: add the bot to
        the Finzora channel as admin, post any message in it, then call
        this — the channel's chat.id will be in the response."""
        resp = self._client.get(f"{self._base_url}/getUpdates")
        resp.raise_for_status()
        return resp.json()

    def get_me(self) -> dict:
        """Verifies the bot token is valid without sending a message —
        used by the /health endpoint."""
        resp = self._client.get(f"{self._base_url}/getMe")
        resp.raise_for_status()
        return resp.json()
