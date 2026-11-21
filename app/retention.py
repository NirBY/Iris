"""Hourly retention (spec 12): old messages, alerts, finished jobs and empty chats are deleted."""

import asyncio
from datetime import UTC, datetime, timedelta

from loguru import logger
from sqlalchemy import ColumnElement, delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Alert, Chat, Job, Message, SkippedGroup
from app.events import bus
from app.settings_store import get_setting

JOB_RETENTION = timedelta(days=7)  # finished jobs
FAILED_JOB_RETENTION = timedelta(days=30)  # failed/dead jobs keep their error visible longer
# Finished schedule runs are recorded in schedule_runs; their job rows only add load (~12k a day).
SCHEDULE_JOB_RETENTION = timedelta(hours=1)
JOB_DELETE_BATCH = 500  # short write transactions, so other writers are not blocked for seconds
INTERVAL_SECONDS = 3600


async def run_retention(
    factory: async_sessionmaker[AsyncSession], now: datetime | None = None
) -> dict[str, int]:
    """One pass. Deleting a message cascades to its classifications, receipts and search row
    (FK cascade + FTS trigger).

    A message is kept while ANY alert still references it: the alert row cascades with its
    message, so deleting the message early would cut the alert's own retention short. Alerts
    are removed first, by `retention.alert_days`, which then frees their messages."""
    now = (now or datetime.now(UTC)).replace(tzinfo=None)  # the database stores naive UTC
    async with factory() as db:
        message_days = int(await get_setting(db, "retention.message_days"))
        message_hours = int(await get_setting(db, "retention.message_hours"))
        message_age = (
            timedelta(hours=message_hours) if message_hours else timedelta(days=message_days)
        )
        alert_days = int(await get_setting(db, "retention.alert_days"))

        alerts = await db.execute(
            delete(Alert).where(Alert.created_at < now - timedelta(days=alert_days))
        )
        message_filters = [
            Message.sent_at < now - message_age,
            Message.id.not_in(select(Alert.message_id)),
        ]
        message_filters.extend(
            [
                Message.status.in_(("done", "skipped", "failed")),
                Message.verdict.is_distinct_from("review"),
                Message.id.not_in(
                    select(Job.payload["message_id"].as_integer()).where(
                        Job.type == "process_message",
                        Job.status.in_(("queued", "running")),
                        Job.payload["message_id"].as_integer().is_not(None),
                    )
                ),
            ]
        )
        messages = await db.execute(delete(Message).where(*message_filters))
        chats = await db.execute(
            delete(Chat).where(
                Chat.id.not_in(select(Message.chat_id)),
                Chat.id.not_in(select(SkippedGroup.chat_id)),
            )
        )
        await db.commit()
    jobs = await _delete_finished_jobs(factory, now)
    result = {
        "alerts": int(alerts.rowcount),  # type: ignore[attr-defined]
        "messages": int(messages.rowcount),  # type: ignore[attr-defined]
        "jobs": jobs,
        "chats": int(chats.rowcount),  # type: ignore[attr-defined]
    }
    if any(result.values()):
        logger.info("retention removed {}", result)
        bus.publish("messages", "alerts", "jobs", "chats", "stats", "review")
    return result


def _expired_job(now: datetime) -> ColumnElement[bool]:
    finished = Job.status.in_(("done", "cancelled"))
    return or_(
        finished & (Job.type == "run_schedule") & (Job.created_at < now - SCHEDULE_JOB_RETENTION),
        finished & (Job.created_at < now - JOB_RETENTION),
        Job.status.in_(("failed", "dead")) & (Job.created_at < now - FAILED_JOB_RETENTION),
    )


async def _delete_finished_jobs(factory: async_sessionmaker[AsyncSession], now: datetime) -> int:
    removed = 0
    while True:
        async with factory() as db:
            # Ids are read first: MySQL rejects LIMIT inside an IN subquery.
            ids = list(
                await db.scalars(
                    select(Job.id).where(_expired_job(now)).order_by(Job.id).limit(JOB_DELETE_BATCH)
                )
            )
            if ids:
                await db.execute(delete(Job).where(Job.id.in_(ids)))
                await db.commit()
        removed += len(ids)
        if len(ids) < JOB_DELETE_BATCH:
            return removed
        await asyncio.sleep(0)  # let queued writers in between batches


async def retention_loop(factory: async_sessionmaker[AsyncSession]) -> None:
    while True:
        try:
            await run_retention(factory)
        except Exception:
            logger.exception("retention pass failed")
        await asyncio.sleep(INTERVAL_SECONDS)
