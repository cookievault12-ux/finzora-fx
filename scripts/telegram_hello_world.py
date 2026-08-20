#!/usr/bin/env python3
"""Phase 1 acceptance check (spec section 97, item 13): send a Telegram
message to prove the bot -> Finzora channel path works end to end.

Usage:
    1. Fill TELEGRAM_BOT_TOKEN in .env (from @BotFather).
    2. Add the bot to your Finzora channel as an admin.
    3. Post any message in the channel, then run:
           python scripts/telegram_hello_world.py --discover-chat-id
       to find TELEGRAM_CHAT_ID and add it to .env.
    4. Run again without the flag to send the hello-world message:
           python scripts/telegram_hello_world.py
"""

from __future__ import annotations

import argparse
import sys

from src.telegram.client import TelegramClient


def discover_chat_id() -> None:
    client = TelegramClient()
    try:
        updates = client.get_updates()
    finally:
        client.close()
    chats = {
        u["message"]["chat"]["id"]: u["message"]["chat"].get("title", u["message"]["chat"].get("type"))
        for u in updates.get("result", [])
        if "message" in u
    }
    if not chats:
        print("No updates found. Post a message in the Finzora channel (with the bot added as admin) and try again.")
        sys.exit(1)
    print("Found chat IDs — set TELEGRAM_CHAT_ID to the one matching your Finzora channel:")
    for chat_id, title in chats.items():
        print(f"  {chat_id}  ({title})")


def send_hello_world() -> None:
    client = TelegramClient()
    try:
        result = client.send_message("FINZORA FX — hello world. Bot is connected and posting.")
    finally:
        client.close()
    if result.get("ok"):
        print("Sent successfully.")
    else:
        print(f"Telegram API returned an error: {result}")
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--discover-chat-id", action="store_true")
    args = parser.parse_args()
    if args.discover_chat_id:
        discover_chat_id()
    else:
        send_hello_world()
