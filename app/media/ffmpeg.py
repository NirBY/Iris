"""ffmpeg/ffprobe helpers (async subprocesses, never a shell)."""

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path

from app.jobs.queue import PermanentError

_TIMEOUT = 120.0
_MAX_CONCURRENT = 2  # decoders are CPU/memory heavy: never more than this at once
_slots: asyncio.Semaphore | None = None
# Only local files/pipes: a crafted playlist or concat file must not make ffmpeg fetch URLs.
_SAFE_INPUT = ("-protocol_whitelist", "file,pipe")

# Magic-number allowlist. ffmpeg sniffs content, not extensions, and text-based "containers"
# (HLS playlists, ffconcat scripts) can name other local files, so only real media is accepted.
_SIGNATURES: tuple[tuple[int, bytes], ...] = (
    (4, b"ftyp"),  # mp4, m4a, 3gp, mov
    (0, b"OggS"),
    (0, b"ID3"),
    (0, b"fLaC"),
    (0, b"\x1a\x45\xdf\xa3"),  # mkv/webm
    (0, b"RIFF"),  # wav, webp, avi
    (0, b"GIF8"),
    (0, b"\x89PNG"),
    (0, b"\xff\xd8\xff"),  # jpeg
    (0, b"#!AMR"),
)


@dataclass(frozen=True)
class MediaInfo:
    duration: float | None
    has_audio: bool
    has_video: bool


def _sniff(path: Path) -> None:
    with path.open("rb") as fh:
        head = fh.read(16)
    is_mpeg_frames = len(head) > 1 and head[0] == 0xFF and head[1] & 0xE0 == 0xE0  # mp3/aac
    if not is_mpeg_frames and not any(head[o : o + len(sig)] == sig for o, sig in _SIGNATURES):
        raise PermanentError("unsupported media format")


async def _check(path: Path) -> None:
    await asyncio.to_thread(_sniff, path)


async def _run(*argv: str) -> tuple[bytes, bytes]:
    global _slots
    if _slots is None:
        _slots = asyncio.Semaphore(_MAX_CONCURRENT)
    async with _slots:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=_TIMEOUT)
        except BaseException as exc:  # timeout, or the worker was cancelled mid-run
            proc.kill()
            await asyncio.shield(proc.wait())
            if isinstance(exc, TimeoutError):
                raise PermanentError("media processing timed out") from exc
            raise
    if proc.returncode != 0:
        # stderr describes the container, never message text; only its last line is kept.
        last = err.decode(errors="replace").strip().splitlines()[-1:] or [""]
        raise PermanentError(f"ffmpeg failed: {last[0][:120]}")
    return out, err


async def probe(path: Path) -> MediaInfo:
    await _check(path)
    out, _ = await _run(
        "ffprobe", "-v", "error", *_SAFE_INPUT,
        "-show_entries", "format=duration:stream=codec_type", "-of", "json", str(path),
    )  # fmt: skip
    data = json.loads(out or b"{}")
    kinds = {s.get("codec_type") for s in data.get("streams", [])}
    try:
        duration: float | None = float(data["format"]["duration"])
    except (KeyError, TypeError, ValueError):
        duration = None
    return MediaInfo(duration=duration, has_audio="audio" in kinds, has_video="video" in kinds)


async def extract_audio(src: Path, dst: Path) -> None:
    """Mono 16 kHz 64 kbps MP3: small, and what the transcription APIs handle best."""
    await _check(src)
    await _run(
        "ffmpeg", "-nostdin", "-y", "-loglevel", "error", *_SAFE_INPUT, "-i", str(src),
        "-vn", "-ac", "1", "-ar", "16000", "-c:a", "libmp3lame", "-b:a", "64k", str(dst),
    )  # fmt: skip


async def image_to_jpeg(src: Path, dst: Path, max_dim: int = 2000) -> None:
    """First frame as a bounded JPEG: converts webp/gif/png and keeps request sizes small."""
    await _check(src)
    await _run(
        "ffmpeg", "-nostdin", "-y", "-loglevel", "error", *_SAFE_INPUT, "-i", str(src),
        "-frames:v", "1", "-vf", f"scale='min({max_dim},iw)':'-2'", "-q:v", "3", str(dst),
    )  # fmt: skip
