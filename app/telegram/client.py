"""Thin Telegram Bot API client for alert delivery. Keep all Telegram endpoint shapes here.

The bot token is part of the request URL, so it is validated before use, never put into an
error message, and httpx's per-request INFO log line (which prints the URL) is silenced.
"""

import logging
import re
import time
from typing import Any

import httpx

from app.metrics import record_provider

# httpx logs "POST <url>" at INFO; the URL carries the bot token.
logging.getLogger("httpx").setLevel(logging.WARNING)

_BASE_URL = "https://api.telegram.org"
_TIMEOUT = httpx.Timeout(20.0)
_TOKEN_RE = re.compile(r"\d{3,15}:[A-Za-z0-9_-]{20,100}")
_MAX_TEXT = 4096  # Telegram's sendMessage limit


class TelegramError(Exception):
    def __init__(self, status: int | None, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.message = message
        self.retry_after = retry_after


def validate_token(token: str) -> str:
    token = token.strip()
    if not _TOKEN_RE.fullmatch(token):
        raise ValueError("not a valid Telegram bot token (expected 123456:ABC-DEF...)")
    return token


class TelegramClient:
    def __init__(self, bot_token: str, transport: httpx.AsyncBaseTransport | None = None):
        self._path = f"/bot{validate_token(bot_token)}"
        self._client = httpx.AsyncClient(base_url=_BASE_URL, timeout=_TIMEOUT, transport=transport)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def send_text(self, chat_id: str, text: str) -> None:
        """Send plain text (no parse_mode, so message content cannot break formatting)."""
        started = time.perf_counter()
        try:
            r = await self._client.post(
                f"{self._path}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": text[:_MAX_TEXT],
                    "disable_web_page_preview": True,
                },
            )
        except httpx.HTTPError as exc:
            record_provider("telegram", "sendMessage", "error", time.perf_counter() - started)
            raise TelegramError(None, f"Telegram unreachable: {exc.__class__.__name__}") from exc
        record_provider(
            "telegram", "sendMessage", str(r.status_code), time.perf_counter() - started
        )
        if r.status_code >= 400:
            raise _error(r)


def _error(r: httpx.Response) -> TelegramError:
    # Only Telegram's short "description" and "retry_after" are surfaced, never raw bodies.
    detail, retry_after = f"HTTP {r.status_code}", None
    try:
        body: Any = r.json()
    except ValueError:
        body = None
    if isinstance(body, dict):
        if isinstance(body.get("description"), str):
            detail = body["description"][:200]
        params = body.get("parameters")
        if isinstance(params, dict) and isinstance(params.get("retry_after"), int | float):
            retry_after = float(params["retry_after"])
    return TelegramError(r.status_code, detail, retry_after)
