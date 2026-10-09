import asyncio
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select

from app.db.models import Message, StoredMedia
from tests.test_messages_api import seed


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
