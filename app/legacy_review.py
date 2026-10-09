"""Startup quarantine of old skipped messages whose original type was lost."""

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Message


async def quarantine_legacy_unknowns(db: AsyncSession) -> None:
    await db.execute(
        update(Message)
        .where(
            Message.type == "other",
            Message.status == "skipped",
            Message.verdict.is_(None),
            Message.raw_type.is_(None),
        )
        .values(
            status="done",
            verdict="review",
            skip_reason=None,
            review_reason="Unknown legacy message; original type and skip reason unavailable",
        )
    )
    await db.commit()
