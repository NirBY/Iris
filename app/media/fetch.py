"""Per-job temp directory and media download. Media never lives outside {DATA_DIR}/tmp/{job_id}/."""

import asyncio
import shutil
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from app.jobs.queue import PermanentError, TransientError
from app.openwa.client import MediaTooLarge, OpenWAClient, OpenWAError

MAX_MEDIA_BYTES = 25 * 1024 * 1024  # also OpenAI's transcription upload limit
MAX_AUDIO_SECONDS = 15 * 60


class MediaSkipped(Exception):
    """Media that Iris deliberately does not process (too large / too long)."""


@asynccontextmanager
async def job_tmpdir(data_dir: Path, job_id: int) -> AsyncIterator[Path]:
    """Temp dir for one job, always removed afterwards (success, failure or cancellation)."""
    path = data_dir / "tmp" / str(job_id)
    await asyncio.to_thread(path.mkdir, parents=True, exist_ok=True)
    try:
        yield path
    finally:
        await asyncio.shield(asyncio.to_thread(shutil.rmtree, path, True))


async def download(
    client: OpenWAClient, session_id: str, chat_id: str, message_ref: str, dest: Path
) -> str:
    """Download one message's media. Maps OpenWA failures to job error semantics."""
    try:
        return await client.download_media(session_id, chat_id, message_ref, dest, MAX_MEDIA_BYTES)
    except MediaTooLarge as exc:
        raise MediaSkipped(f"media too large ({exc.size} bytes)") from exc
    except OpenWAError as exc:
        if exc.status in (400, 404, 410):  # OpenWA has no copy: retrying cannot help
            raise PermanentError(
                "OpenWA has no stored media for this message (check its inbound media storage)"
            ) from exc
        if exc.status in (401, 403):
            raise PermanentError("OpenWA rejected the API key") from exc
        raise TransientError(f"OpenWA media download failed: {exc.message}") from exc
