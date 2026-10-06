from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.engine import make_engine, make_session_factory
from app.db.migrate import upgrade_head
from app.db.models import Chat, Message


@pytest.fixture
async def engine(tmp_path: Path) -> AsyncEngine:
    url = f"sqlite+aiosqlite:///{tmp_path / 't.db'}"
    await __import__("asyncio").to_thread(upgrade_head, url)
    return make_engine(url)


async def _insert(engine: AsyncEngine, body: str) -> int:

    async with make_session_factory(engine)() as s:
        chat = Chat(wa_chat_id="c1", name="g")
        s.add(chat)
        await s.flush()
        m = Message(
            wa_message_id="m1",
            chat_id=chat.id,
            type="text",
            text=body,
            sent_at=datetime.now(UTC),
        )
        s.add(m)
        await s.commit()
        return m.id


async def _hits(engine: AsyncEngine, q: str) -> int:
    async with engine.connect() as c:
        r = await c.execute(
            text("SELECT count(*) FROM messages_fts WHERE messages_fts MATCH :q"), {"q": q}
        )
        return int(r.scalar_one())


async def test_wal_enabled(engine: AsyncEngine) -> None:
    async with engine.connect() as c:
        assert (await c.execute(text("PRAGMA journal_mode"))).scalar_one() == "wal"


async def test_fts_hebrew_search_and_redaction(engine: AsyncEngine) -> None:
    mid = await _insert(engine, "שלום עולם hello")
    assert await _hits(engine, "שלום") == 1
    assert await _hits(engine, "hello") == 1
    async with engine.begin() as c:
        await c.execute(
            text("UPDATE messages SET text='[redacted]', redacted=1 WHERE id=:i"), {"i": mid}
        )
    assert await _hits(engine, "שלום") == 0
    assert await _hits(engine, "redacted") == 0
