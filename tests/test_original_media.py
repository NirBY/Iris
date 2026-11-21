import asyncio
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select

from app.db.models import Message, StoredMedia
from tests.test_messages_api import seed


async def test_preview_uses_retained_copy_even_when_openwa_lost_it(
    app_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.config import get_settings
    from app.media.store import LocalStore

    await seed(app_client)
    cfg = get_settings()
    source = cfg.data_dir / "preview-test.webp"
    source.write_bytes(b"RIFFxxxxWEBPexample")
    store = LocalStore(cfg.data_dir / "media")
    await store.put("preview-test.webp", source, "image/webp")
    async with app_client.app.state.session_factory() as db:
        m = (await db.scalars(select(Message).where(Message.type == "image"))).one()
        mid = m.id
        db.add(
            StoredMedia(
                message_id=mid,
                backend="local",
                location="",
                key="preview-test.webp",
                content_type="image/webp",
                kind="image",
                size_bytes=18,
                sha256="a" * 64,
            )
        )
        await db.commit()

    async def fail(*args: Any, **kwargs: Any) -> str:
        pytest.fail("The saved copy must not depend on OpenWA")

    monkeypatch.setattr("app.api.media.fetch_original", fail)
    response = await app_client.get(f"/api/media/message/{mid}", headers={"Range": "bytes=0-3"})
    assert response.status_code == 206 and response.content == b"RIFF"
    assert response.headers["content-type"].startswith("image/webp")


async def test_original_media_reads_without_retaining_or_changing_message(
    app_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    await seed(app_client)
    async with app_client.app.state.session_factory() as db:
        message = (await db.scalars(select(Message).where(Message.type == "image"))).one()
        mid, before = message.id, (message.status, message.verdict)
    paths = []

    async def fetch(db: Any, message: Any, key: bytes, path: Path, **kwargs: Any) -> str:
        paths.append(path)
        await asyncio.to_thread(path.write_bytes, b"RIFFxxxxWEBPexample")
        return "image/webp"

    monkeypatch.setattr("app.api.media.fetch_original", fetch)
    response = await app_client.get(f"/api/media/message/{mid}", headers={"Range": "bytes=0-3"})
    assert response.status_code == 206 and response.content == b"RIFF"
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["content-type"].startswith("image/webp")
    assert all(not path.exists() for path in paths)
    async with app_client.app.state.session_factory() as db:
        message = await db.get(Message, mid)
        assert message and (message.status, message.verdict) == before
        assert not (await db.scalars(select(StoredMedia))).all()


async def test_original_media_never_fetches_withheld_content(
    app_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    await seed(app_client)
    async with app_client.app.state.session_factory() as db:
        message = (await db.scalars(select(Message).where(Message.type == "image"))).one()
        message.redacted = True
        mid = message.id
        await db.commit()

    async def fail(*args: Any) -> str:
        pytest.fail("Must not fetch withheld media")

    monkeypatch.setattr("app.api.media.fetch_original", fail)
    assert (await app_client.get(f"/api/media/message/{mid}")).status_code == 404


@pytest.mark.parametrize(
    "reason,status,expected",
    [
        ("OpenWA has no stored media for this message", 404, "OpenWA has no saved copy"),
        ("message has no media reference", 404, "no original media reference"),
        ("OpenWA rejected the API key", 503, "API key checked"),
    ],
)
async def test_original_media_explains_the_actual_failure(
    app_client: Any, monkeypatch: pytest.MonkeyPatch, reason: str, status: int, expected: str
) -> None:
    from app.jobs.queue import PermanentError

    await seed(app_client)
    async with app_client.app.state.session_factory() as db:
        mid = (await db.scalars(select(Message).where(Message.type == "image"))).one().id

    async def fail(*args: Any, **kwargs: Any) -> str:
        raise PermanentError(reason)

    monkeypatch.setattr("app.api.media.fetch_original", fail)
    response = await app_client.get(f"/api/media/message/{mid}")
    assert response.status_code == status and expected in response.json()["detail"]


@pytest.mark.parametrize(
    "payload,mime,disposition",
    [
        (b"%PDF-1.7\nPDF preview", "application/pdf", "inline"),
        (b"<html><script>alert(1)</script></html>", "application/octet-stream", "attachment"),
    ],
)
async def test_document_pdf_preview_and_unknown_format_download(
    app_client: Any, monkeypatch: pytest.MonkeyPatch, payload: bytes, mime: str, disposition: str
) -> None:
    await seed(app_client)
    async with app_client.app.state.session_factory() as db:
        message = (await db.scalars(select(Message).where(Message.type == "image"))).one()
        message.type = "document"
        message.media = {**(message.media or {}), "filename": "../מסמך.pdf"}
        mid = message.id
        await db.commit()
    paths = []

    async def fetch(db: Any, message: Any, key: bytes, path: Path, **kwargs: Any) -> str:
        paths.append(path)
        await asyncio.to_thread(path.write_bytes, payload)
        return mime

    monkeypatch.setattr("app.api.media.fetch_original", fetch)
    response = await app_client.get(f"/api/media/message/{mid}")
    assert response.status_code == 200 and response.content == payload
    assert response.headers["content-type"].startswith(mime)
    assert response.headers["content-disposition"].startswith(disposition)
    assert "../" not in response.headers["content-disposition"]
    assert "sandbox" in response.headers["content-security-policy"]
    assert response.headers["x-content-type-options"] == "nosniff"
    assert all(not path.exists() for path in paths)


def _sticker_zip(path: Path, animation: dict[str, Any]) -> None:
    import json
    import zipfile

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("animation/animation.json", json.dumps(animation))
        archive.writestr("animation/animation.json.trust_token", "token")


ANIMATION = {
    "v": "5.12.1",
    "fr": 60,
    "ip": 0,
    "op": 60,
    "w": 512,
    "h": 512,
    "layers": [{"ty": 4}],
    "assets": [
        {"id": "comp_0", "layers": []},
        {"id": "image_0", "u": "https://example.com/", "p": "tracker.png"},
        {"id": "image_1", "u": "", "p": "data:image/png;base64,iVBORw0KGgo="},
    ],
}


async def _sticker(app_client: Any) -> int:
    await seed(app_client)
    async with app_client.app.state.session_factory() as db:
        message = (await db.scalars(select(Message).where(Message.type == "image"))).one()
        message.type = "sticker"
        await db.commit()
        return message.id


async def test_animated_sticker_plays_from_its_lottie_json_without_external_assets(
    app_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    mid = await _sticker(app_client)

    async def fetch(db: Any, message: Any, key: bytes, path: Path, **kwargs: Any) -> str:
        await asyncio.to_thread(_sticker_zip, path, ANIMATION)
        return "application/was"

    monkeypatch.setattr("app.api.media.fetch_original", fetch)
    original = await app_client.get(f"/api/media/message/{mid}")
    assert original.status_code == 415 and "Animated sticker" in original.json()["detail"]
    response = await app_client.get(f"/api/media/message/{mid}/animation")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    data = response.json()
    assert data["layers"] == [{"ty": 4}]
    assert [a["id"] for a in data["assets"]] == ["comp_0", "image_1"]


async def test_animation_rejects_non_stickers_and_oversized_or_invalid_archives(
    app_client: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from app.media.lottie import NotLottie, read_animation

    mid = await _sticker(app_client)
    payload: dict[str, Any] = {"body": b"not a zip"}

    async def fetch(db: Any, message: Any, key: bytes, path: Path, **kwargs: Any) -> str:
        await asyncio.to_thread(path.write_bytes, payload["body"])
        return "application/was"

    monkeypatch.setattr("app.api.media.fetch_original", fetch)
    assert (await app_client.get(f"/api/media/message/{mid}/animation")).status_code == 415

    bomb = tmp_path / "bomb.was"
    _sticker_zip(bomb, {"layers": [], "pad": "0" * (5 * 1024 * 1024)})
    with pytest.raises(NotLottie, match="too large"):
        read_animation(bomb)

    async with app_client.app.state.session_factory() as db:
        message = await db.get(Message, mid)
        assert message
        message.type = "image"
        await db.commit()
    assert (await app_client.get(f"/api/media/message/{mid}/animation")).status_code == 404


async def test_lottie_sticker_gets_a_clear_review_reason(tmp_path: Path) -> None:
    from app.jobs.queue import PermanentError
    from app.media import ffmpeg

    sticker = tmp_path / "sticker.was"
    _sticker_zip(sticker, ANIMATION)
    with pytest.raises(PermanentError, match=r"Animated \(Lottie\) sticker"):
        await ffmpeg.image_to_jpeg(sticker, tmp_path / "out.jpg")
