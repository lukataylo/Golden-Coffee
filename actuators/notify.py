"""Staff notifications via Telegram bot.

Pre-hackathon setup (do once):
  1. Message @BotFather on Telegram -> /newbot -> copy the token into TELEGRAM_TOKEN.
  2. Send any message to your new bot, then open
     https://api.telegram.org/bot<TOKEN>/getUpdates and copy the numeric
     "chat":{"id":...} into TELEGRAM_CHAT_ID  (or run `python -m actuators.notify --chat-id`).
  3. `python -m actuators.notify "test"` to confirm it lands.

Sending is a single requests.post — no SDK needed.
"""
from __future__ import annotations

import os
import sys

import requests

try:  # load .env if present (local dev / demo machine)
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
_API = "https://api.telegram.org/bot{token}/{method}"


def notify_staff(text: str) -> bool:
    """Send a staff alert to Telegram. Degrades gracefully (prints) if unconfigured."""
    if not (TELEGRAM_TOKEN and TELEGRAM_CHAT_ID):
        print(f"[notify] (Telegram not configured) would send: {text}")
        return False
    try:
        resp = requests.post(
            _API.format(token=TELEGRAM_TOKEN, method="sendMessage"),
            json={"chat_id": TELEGRAM_CHAT_ID, "text": f"☕ {text}"},
            timeout=3,
        )
        ok = resp.ok
        if not ok:
            print(f"[notify] telegram error {resp.status_code}: {resp.text[:120]}")
        return ok
    except Exception as exc:
        print(f"[notify] telegram failed: {exc}")
        return False


def _print_chat_id() -> None:
    """Helper: print recent chat ids from getUpdates so you can fill TELEGRAM_CHAT_ID."""
    if not TELEGRAM_TOKEN:
        print("set TELEGRAM_TOKEN first")
        return
    r = requests.get(_API.format(token=TELEGRAM_TOKEN, method="getUpdates"), timeout=5)
    for upd in r.json().get("result", []):
        chat = (upd.get("message") or upd.get("channel_post") or {}).get("chat", {})
        if chat:
            print(f"chat_id={chat.get('id')}  ({chat.get('type')}: {chat.get('title') or chat.get('username')})")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--chat-id":
        _print_chat_id()
    else:
        notify_staff(sys.argv[1] if len(sys.argv) > 1 else "Caffe Steve test alert")
