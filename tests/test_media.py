import os
from pathlib import Path

import httpx
import pytest
import respx

from app.jobs.queue import PermanentError, TransientError
from app.media import ffmpeg
from app.media.fetch import MediaSkipped, download, job_tmpdir
from app.openwa.client import OpenWAClient

FIX = Path(__file__).parent / "fixtures" / "media"
MEDIA_URL = r"https://wa\.x/api/sessions/s1/messages/chat%40lid/true_chat%40lid_ABC/media"


async def test_probe_video_with_and_without_audio() -> None:
    a = await ffmpeg.probe(FIX / "video_audio.mp4")
    assert a.has_audio and a.has_video and a.duration and 1.5 < a.duration < 2.5
    s = await ffmpeg.probe(FIX / "video_silent.mp4")
    assert s.has_video and not s.has_audio


async def test_extract_audio_makes_mono_mp3(tmp_path: Path) -> None:
    out = tmp_path / "a.mp3"
    await ffmpeg.extract_audio(FIX / "video_audio.mp4", out)
    info = await ffmpeg.probe(out)
    assert info.has_audio and not info.has_video and out.stat().st_size > 0


async def test_extract_audio_from_silent_video_fails_cleanly(tmp_path: Path) -> None:
    with pytest.raises(PermanentError):
        await ffmpeg.extract_audio(FIX / "video_silent.mp4", tmp_path / "a.mp3")


@pytest.mark.parametrize("name", ["image.png", "sticker.webp", "anim.gif"])
async def test_image_to_jpeg_handles_png_webp_and_gif(tmp_path: Path, name: str) -> None:
    out = tmp_path / "o.jpg"
    await ffmpeg.image_to_jpeg(FIX / name, out)
    assert out.read_bytes()[:3] == b"\xff\xd8\xff"


async def test_corrupt_media_raises_permanent(tmp_path: Path) -> None:
    bad = tmp_path / "bad.bin"
    bad.write_bytes(b"not media at all")
    with pytest.raises(PermanentError):
        await ffmpeg.probe(bad)
    with pytest.raises(PermanentError):
        await ffmpeg.image_to_jpeg(bad, tmp_path / "x.jpg")


async def test_tmpdir_removed_on_success_and_on_exception(tmp_path: Path) -> None:
    async with job_tmpdir(tmp_path, 5) as d:
        (d / "f").write_bytes(b"x")
        assert d.exists()
    assert not (tmp_path / "tmp" / "5").exists()
    with pytest.raises(RuntimeError):
        async with job_tmpdir(tmp_path, 6) as d:
            (d / "f").write_bytes(b"x")
            raise RuntimeError("boom")
    assert not (tmp_path / "tmp" / "6").exists()


def _client() -> OpenWAClient:
    return OpenWAClient("https://wa.x", "key")


@respx.mock
async def test_download_streams_and_returns_real_content_type(tmp_path: Path) -> None:
    respx.get(url__regex=MEDIA_URL).mock(
        return_value=httpx.Response(
            200, content=b"\x89PNG....", headers={"content-type": "image/png"}
        )
    )
    dest = tmp_path / "m"
    ctype = await download(_client(), "s1", "chat@lid", "true_chat@lid_ABC", dest)
    assert ctype == "image/png" and dest.read_bytes() == b"\x89PNG...."


@respx.mock
async def test_download_too_large_is_skipped_and_cleaned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.media.fetch.MAX_MEDIA_BYTES", 10)
    respx.get(url__regex=MEDIA_URL).mock(return_value=httpx.Response(200, content=b"x" * 50))
    dest = tmp_path / "m"
    with pytest.raises(MediaSkipped):
        await download(_client(), "s1", "chat@lid", "true_chat@lid_ABC", dest)
    assert not dest.exists()


@respx.mock
@pytest.mark.parametrize(
    ("status", "exc"), [(404, PermanentError), (401, PermanentError), (502, TransientError)]
)
async def test_download_error_mapping(tmp_path: Path, status: int, exc: type[Exception]) -> None:
    respx.get(url__regex=MEDIA_URL).mock(return_value=httpx.Response(status))
    with pytest.raises(exc):
        await download(_client(), "s1", "chat@lid", "true_chat@lid_ABC", tmp_path / "m")


@respx.mock
async def test_download_network_error_is_transient(tmp_path: Path) -> None:
    respx.get(url__regex=MEDIA_URL).mock(side_effect=httpx.ConnectError("x"))
    with pytest.raises(TransientError):
        await download(_client(), "s1", "chat@lid", "true_chat@lid_ABC", tmp_path / "m")


def test_fixtures_are_small() -> None:
    assert sum(f.stat().st_size for f in FIX.iterdir()) < 100_000 and os.listdir(FIX)
