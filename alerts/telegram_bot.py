"""Telegram push notifications (spec M9, Phase 2).

Sends plain messages via the Telegram Bot HTTP API. Token and chat id are read
from the environment (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID) and never logged.
If either is missing, sending is a no-op that returns False so callers can still
record the alert in the database for audit.
"""
from __future__ import annotations

import logging
import os

import requests

logger = logging.getLogger(__name__)

_TIMEOUT = 15


def _token() -> str | None:
    v = os.getenv("TELEGRAM_BOT_TOKEN")
    return v.strip() if v else None


def _chat_id() -> str | None:
    v = os.getenv("TELEGRAM_CHAT_ID")
    return v.strip() if v else None


def is_configured() -> bool:
    return _token() is not None and _chat_id() is not None


def send(text: str) -> bool:
    """Send a message. Returns True on success, False if unconfigured/failed."""
    token, chat_id = _token(), _chat_id()
    if not token or not chat_id:
        logger.info("Telegram not configured; message not pushed")
        return False
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        return True
    except Exception as exc:
        logger.warning("Telegram send failed: %s", exc)
        return False
