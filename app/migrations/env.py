import asyncio

from alembic import context
from sqlalchemy.engine import Connection

from app.db.engine import make_engine
from app.db.models import Base

target_metadata = Base.metadata


def _include_object(obj: object, name: str | None, type_: str, *_: object) -> bool:
    # The FTS5 virtual table and its shadow tables are managed by hand in migrations.
    return not (type_ == "table" and name is not None and name.startswith("messages_fts"))


def _run(connection: Connection) -> None:
    context.configure(
        connection=connection, target_metadata=target_metadata, include_object=_include_object
    )
    with context.begin_transaction():
        context.run_migrations()


async def _run_async() -> None:
    url = context.config.attributes.get("url")
    engine = make_engine(url)
    async with engine.connect() as conn:
        await conn.run_sync(_run)
    await engine.dispose()


asyncio.run(_run_async())
