"""OpenAI audio transcription (multipart upload, language auto-detected)."""

import asyncio
import time
from pathlib import Path

import httpx

from app.jobs.queue import TransientError
from app.metrics import record_provider
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
        started = time.perf_counter()
        try:
            r = await self._client.post(
                URL,
                data={"model": self._model, "response_format": fmt},  # no language: auto-detect
                files={"file": (path.name, data, mime_type)},
            )
        except httpx.HTTPError as exc:
            record_provider("openai", "transcriptions", "error", time.perf_counter() - started)
            raise TransientError(f"transcription unreachable: {exc.__class__.__name__}") from exc
        record_provider(
            "openai", "transcriptions", str(r.status_code), time.perf_counter() - started
        )
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
