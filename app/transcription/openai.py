"""OpenAI audio transcription (multipart upload, language auto-detected)."""

import asyncio
from pathlib import Path

import httpx

from app.jobs.queue import TransientError
from app.transcription.base import TranscriptResult, raise_for_status

URL = "https://api.openai.com/v1/audio/transcriptions"
_TIMEOUT = httpx.Timeout(300.0, connect=15.0)


class OpenAITranscriber:
    name = "openai"

    def __init__(
        self, api_key: str, model: str, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self._model = model
        self._client = httpx.AsyncClient(
            headers={"Authorization": f"Bearer {api_key}"}, timeout=_TIMEOUT, transport=transport
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def transcribe(self, path: Path, mime_type: str) -> TranscriptResult:
        data = await asyncio.to_thread(path.read_bytes)
        # whisper-1 can return language and duration (verbose_json); gpt-4o models plain json only.
        fmt = "verbose_json" if self._model == "whisper-1" else "json"
        try:
            r = await self._client.post(
                URL,
                data={"model": self._model, "response_format": fmt},  # no language: auto-detect
                files={"file": (path.name, data, mime_type)},
            )
        except httpx.HTTPError as exc:
            raise TransientError(f"transcription unreachable: {exc.__class__.__name__}") from exc
        raise_for_status("openai transcription", r)
        try:
            body = r.json()
            text = str(body["text"]).strip()
        except (KeyError, ValueError, TypeError) as exc:
            raise TransientError("transcription returned an unexpected response") from exc
        duration = body.get("duration")
        return TranscriptResult(
            text=text,
            language=body.get("language") if isinstance(body.get("language"), str) else None,
            duration_seconds=float(duration) if isinstance(duration, int | float) else None,
        )
