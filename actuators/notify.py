"""Staff notifications via Slack Incoming Webhook (simplest) or Telegram bot.

Slack:    create app -> Incoming Webhooks -> copy URL into SLACK_WEBHOOK_URL.
Telegram: BotFather -> TELEGRAM_TOKEN; message the bot, read chat_id from getUpdates
          into TELEGRAM_CHAT_ID.
Both are a single requests.post — no SDK needed.
"""
from __future__ import annotations

import os

import requests

SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL", "")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")


def notify_staff(text: str) -> bool:
    sent = False
    if SLACK_WEBHOOK_URL:
        try:
            requests.post(SLACK_WEBHOOK_URL, json={"text": f"☕ {text}"}, timeout=3)
            sent = True
        except Exception as exc:
            print(f"[notify] slack failed: {exc}")
    if TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:
        try:
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={"chat_id": TELEGRAM_CHAT_ID, "text": f"☕ {text}"},
                timeout=3,
            )
            sent = True
        except Exception as exc:
            print(f"[notify] telegram failed: {exc}")
    if not sent:
        print(f"[notify] (no channel configured) would send: {text}")
    return sent


if __name__ == "__main__":
    notify_staff("Golden Coffee test alert")
