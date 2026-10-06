"""Thin OpenWA REST client (X-API-Key auth). Keep all OpenWA endpoint shapes here."""

from typing import Any

import httpx

# Cloudflare in front of OpenWA rejects default library User-Agents.
_UA = "iris/1.0"
_TIMEOUT = httpx.Timeout(20.0)
WEBHOOK_EVENTS = ["message.received", "message.sent"]


class OpenWAError(Exception):
    def __init__(self, status: int | None, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


class OpenWAClient:
    def __init__(
        self, base_url: str, api_key: str, transport: httpx.AsyncBaseTransport | None = None
    ):
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"X-API-Key": api_key, "User-Agent": _UA},
            timeout=_TIMEOUT,
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _request(self, method: str, path: str, **kw: Any) -> Any:
        try:
            r = await self._client.request(method, path, **kw)
        except httpx.HTTPError as exc:
            raise OpenWAError(None, f"OpenWA unreachable: {exc.__class__.__name__}") from exc
        if r.status_code >= 400:
            try:
                detail = r.json().get("message", r.text)
            except ValueError:
                detail = r.text
            raise OpenWAError(r.status_code, str(detail)[:300])
        return r.json() if r.content else None

    async def register_webhook(self, session_id: str, url: str, secret: str) -> str:
        """Create a webhook for the session and return its id."""
        data = await self._request(
            "POST",
            f"/api/sessions/{session_id}/webhooks",
            json={"url": url, "events": WEBHOOK_EVENTS, "secret": secret, "retryCount": 3},
        )
        body = data.get("data", data) if isinstance(data, dict) else {}
        return str(body.get("id", ""))

    async def send_text(self, session_id: str, chat_id: str, text: str) -> None:
        await self._request(
            "POST",
            f"/api/sessions/{session_id}/messages/send-text",
            json={"chatId": chat_id, "text": text},
        )
