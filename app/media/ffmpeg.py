"""ffmpeg/ffprobe helpers (async subprocesses, never a shell)."""

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path

from app.jobs.queue import PermanentError

_TIMEOUT = 120.0


@dataclass(frozen=True)
class MediaInfo:
    duration: float | None
    has_audio: bool
    has_video: bool


async def _run(*argv: str) -> tuple[bytes, bytes]:
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=_TIMEOUT)
    except TimeoutError as exc:
        proc.kill()
        await proc.wait()
        raise PermanentError("media processing timed out") from exc
    if proc.returncode != 0:
        # stderr describes the container, never message text; still only its first line is kept.
        first = err.decode(errors="replace").strip().splitlines()[-1:] or [""]
        raise PermanentError(f"ffmpeg failed: {first[0][:120]}")
    return out, err


async def probe(path: Path) -> MediaInfo:
    out, _ = await _run(
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration:stream=codec_type",
        "-of",
        "json",
        str(path),
    )
    data = json.loads(out or b"{}")
    kinds = {s.get("codec_type") for s in data.get("streams", [])}
    try:
        duration: float | None = float(data["format"]["duration"])
    except (KeyError, TypeError, ValueError):
        duration = None
    return MediaInfo(duration=duration, has_audio="audio" in kinds, has_video="video" in kinds)


async def extract_audio(src: Path, dst: Path) -> None:
    """Mono 16 kHz 64 kbps MP3: small, and what the transcription APIs handle best."""
    await _run(
        "ffmpeg",
        "-nostdin",
        "-y",
        "-loglevel",
        "error",
        "-i",
        str(src),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-c:a",
        "libmp3lame",
        "-b:a",
        "64k",
        str(dst),
    )


async def image_to_jpeg(src: Path, dst: Path, max_dim: int = 2000) -> None:
    """First frame as a bounded JPEG: converts webp/gif/png and keeps request sizes small."""
    await _run(
        "ffmpeg",
        "-nostdin",
        "-y",
        "-loglevel",
        "error",
        "-i",
        str(src),
        "-frames:v",
        "1",
        "-vf",
        f"scale='min({max_dim},iw)':'-2'",
        "-q:v",
        "3",
        str(dst),
    )
