"""Cloudflare Workers AI transcription.

UNVERIFIED against the live API (no credentials were available when written). Assumed for
`@cf/openai/whisper-large-v3-turbo`: JSON body `{"audio": "<base64>"}` and a response of
`{"result": {"text": ..., "transcription_info": {"language": ..., "duration": ...}}}`.
Only the configured model's input format is supported (older `@cf/openai/whisper` differs).
"""

import asyncio
import base64
from pathlib import Path
from typing import Any

import httpx

from app.jobs.queue import TransientError
from app.transcription.base import TranscriptResult, raise_for_status

_TIMEOUT = httpx.Timeout(300.0, connect=15.0)


class CloudflareTranscriber:
    name = "cloudflare"

    def __init__(
        self,
        account_id: str,
        api_token: str,
        model: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{model}"
        self._client = httpx.AsyncClient(
            headers={"Authorization": f"Bearer {api_token}"}, timeout=_TIMEOUT, transport=transport
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def transcribe(self, path: Path, mime_type: str) -> TranscriptResult:
        raw = await asyncio.to_thread(path.read_bytes)
        audio = base64.b64encode(raw).decode()
        try:
            r = await self._client.post(self._url, json={"audio": audio})
        except httpx.HTTPError as exc:
            raise TransientError(f"transcription unreachable: {exc.__class__.__name__}") from exc
        raise_for_status("cloudflare transcription", r)
        try:
            body: dict[str, Any] = r.json()
            result = body["result"]
            text = str(result["text"]).strip()
        except (KeyError, ValueError, TypeError) as exc:
            raise TransientError("transcription returned an unexpected response") from exc
        info = result.get("transcription_info") or {}
        duration = info.get("duration")
        return TranscriptResult(
            text=text,
            language=info.get("language") if isinstance(info.get("language"), str) else None,
            duration_seconds=float(duration) if isinstance(duration, int | float) else None,
        )
