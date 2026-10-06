"""Cloudflare Workers AI transcription.

UNVERIFIED against the live API (no credentials were available when written). Assumed for
`@cf/openai/whisper-large-v3-turbo`: JSON body `{"audio": "<base64>"}` and a response of
`{"result": {"text": ..., "transcription_info": {"language": ..., "duration": ...}}}`.
Only the configured model's input format is supported (older `@cf/openai/whisper` differs).
"""

import asyncio
import base64
import re
import time
from pathlib import Path
from typing import Any

import httpx

from app.jobs.queue import TransientError
from app.metrics import record_provider
from app.transcription.base import TranscriptResult, raise_for_status

_TIMEOUT = httpx.Timeout(300.0, connect=15.0)
ACCOUNT_ID_RE = re.compile(r"^[0-9a-f]{32}$")
MODEL_RE = re.compile(r"^@cf/[\w.-]+/[\w.-]+$")


def validate_account_id(v: str) -> str:
    if not ACCOUNT_ID_RE.match(v):
        raise ValueError("Cloudflare account ID is 32 hex characters")
    return v


def validate_model(v: str) -> str:
    if not MODEL_RE.match(v):
        raise ValueError("model looks like @cf/<vendor>/<name>")
    return v


class CloudflareTranscriber:
    name = "cloudflare"

    def __init__(
        self,
        account_id: str,
        api_token: str,
        model: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        # Validated here too, so a bad value can never reshape the URL (path/query injection).
        account_id, model = validate_account_id(account_id), validate_model(model)
        self._url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{model}"
        self._client = httpx.AsyncClient(
            headers={"Authorization": f"Bearer {api_token}"}, timeout=_TIMEOUT, transport=transport
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def transcribe(self, path: Path, mime_type: str) -> TranscriptResult:
        raw = await asyncio.to_thread(path.read_bytes)
        audio = base64.b64encode(raw).decode()
        started = time.perf_counter()
        try:
            r = await self._client.post(self._url, json={"audio": audio})
        except httpx.HTTPError as exc:
            record_provider("cloudflare", "ai_run", "error", time.perf_counter() - started)
            raise TransientError(f"transcription unreachable: {exc.__class__.__name__}") from exc
        record_provider("cloudflare", "ai_run", str(r.status_code), time.perf_counter() - started)
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
