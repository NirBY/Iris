"""Transcriber protocol shared by the providers."""

import contextlib
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import httpx

from app.jobs.queue import PermanentError, TransientError


@dataclass
class TranscriptResult:
    text: str
    language: str | None
    duration_seconds: float | None


class Transcriber(Protocol):
    name: str

    async def transcribe(self, path: Path, mime_type: str) -> TranscriptResult: ...


def raise_for_status(provider: str, r: httpx.Response) -> None:
    """429/5xx are transient (honouring a sane Retry-After); other errors are permanent."""
    if r.status_code < 400:
        return
    if r.status_code == 429 or r.status_code >= 500:
        retry_after: float | None = None
        with contextlib.suppress(ValueError):
            parsed = float(r.headers.get("retry-after", ""))
            if math.isfinite(parsed):
                retry_after = min(max(parsed, 0.0), 3600.0)
        raise TransientError(f"{provider} HTTP {r.status_code}", retry_after=retry_after)
    raise PermanentError(f"{provider} HTTP {r.status_code}")
