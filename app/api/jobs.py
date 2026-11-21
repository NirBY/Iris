"""/api/jobs: failed and dead jobs with their errors, plus manual retry."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.alerts.readiness import DeliveryReadiness, delivery_readiness
from app.db.models import Instance, Job
from app.deps import get_db
from app.jobs.queue import retry_job
from app.schedules import CATALOG, schedule_config
from app.security.auth import admin_user

router = APIRouter(prefix="/api/jobs", tags=["jobs"], dependencies=[Depends(admin_user)])
DB = Annotated[AsyncSession, Depends(get_db)]


DELIVERY_TYPES = {"deliver_alert", "notify_change", "test_alert"}
DELIVERY_SCHEDULES = {"daily_summary", "connection_notifications"}


class JobNote(BaseModel):
    """Why a failed job is stuck, as a code the UI words in the viewer's language."""

    code: str  # uncertain_delivery | sender_removed | sending_not_ready | schedule_off
    delivered: int | None = None
    uncertain: int | None = None
    detail: str | None = None


class JobOut(BaseModel):
    id: int
    type: str
    status: str
    attempts: int
    max_attempts: int
    last_error: str | None
    message_id: int | None
    run_after: datetime
    created_at: datetime
    notes: list[JobNote] = []
    can_retry: bool = True


def _is_delivery(job: Job, payload: dict[str, object]) -> bool:
    return (
        job.type in DELIVERY_TYPES
        or payload.get("schedule_key") in DELIVERY_SCHEDULES
        or "delivered_recipients" in payload
    )


async def _explain(
    db: AsyncSession, job: Job, readiness: dict[str, DeliveryReadiness]
) -> tuple[list[JobNote], bool]:
    payload = job.payload if isinstance(job.payload, dict) else {}
    notes: list[JobNote] = []
    can_retry = True
    if payload.get("delivery_uncertain"):
        # Retries never resend to an unconfirmed recipient, so this job cannot complete.
        notes.append(
            JobNote(
                code="uncertain_delivery",
                delivered=len(payload.get("delivered_recipients") or []),
                uncertain=len(payload.get("uncertain_recipients") or []) or None,
            )
        )
        can_retry = False
    sender_id = payload.get("sender_instance_id")
    if isinstance(sender_id, int) and await db.get(Instance, sender_id) is None:
        notes.append(JobNote(code="sender_removed"))
    if job.status in ("failed", "dead") and _is_delivery(job, payload):
        if "current" not in readiness:
            readiness["current"] = await delivery_readiness(db)
        current = readiness["current"]
        if not current.ready:
            notes.append(JobNote(code="sending_not_ready", detail=current.error))
    key = payload.get("schedule_key")
    if (
        job.type == "run_schedule"
        and isinstance(key, str)
        and key in CATALOG
        and not (await schedule_config(db, key))["enabled"]
    ):
        notes.append(JobNote(code="schedule_off", detail=str(CATALOG[key]["name"])))
        can_retry = False
    return notes, can_retry


@router.get("")
async def list_jobs(db: DB, status: str | None = None, limit: int = 100) -> list[JobOut]:
    """Failed and dead jobs by default (the ones needing attention)."""
    stmt = select(Job).order_by(Job.id.desc()).limit(min(max(limit, 1), 500))
    stmt = (
        stmt.where(Job.status == status)
        if status
        else stmt.where(Job.status.in_(["failed", "dead"]))
    )
    readiness: dict[str, DeliveryReadiness] = {}
    out = []
    for j in (await db.execute(stmt)).scalars():
        notes, can_retry = await _explain(db, j, readiness)
        out.append(
            JobOut(
                id=j.id,
                type=j.type,
                status=j.status,
                attempts=j.attempts,
                max_attempts=j.max_attempts,
                last_error=j.last_error,
                created_at=j.created_at,
                run_after=j.run_after,
                message_id=j.payload.get("message_id")
                if isinstance(j.payload.get("message_id"), int)
                else None,
                notes=notes,
                can_retry=can_retry,
            )
        )
    return out


class RetryAllOut(BaseModel):
    retried: int
    skipped: int


@router.post("/retry-all")
async def retry_all(db: DB) -> RetryAllOut:
    """Retry every failed or dead job, oldest first. Jobs that cannot be retried are skipped.

    A job whose delivery is uncertain may already have reached someone; retrying it in bulk
    could send the same alert or summary twice, so it is left for an individual decision.
    """
    jobs = list(
        (
            await db.execute(select(Job).where(Job.status.in_(["failed", "dead"])).order_by(Job.id))
        ).scalars()
    )
    ids = [job.id for job in jobs]
    readiness: dict[str, DeliveryReadiness] = {}
    retryable = [job.id for job in jobs if (await _explain(db, job, readiness))[1]]
    retried = 0
    for job_id in retryable:
        if await retry_job(db, job_id, manual=True):
            retried += 1
    return RetryAllOut(retried=retried, skipped=len(ids) - retried)


@router.post("/{job_id}/retry")
async def retry(job_id: int, db: DB) -> dict[str, bool]:
    job = await db.get(Job, job_id)
    if job is not None and not (await _explain(db, job, {}))[1]:
        raise HTTPException(
            status_code=409,
            detail="This job cannot complete by retrying; see the explanation on the Jobs page",
        )
    if not await retry_job(db, job_id, manual=True):
        raise HTTPException(status_code=409, detail="Only failed or dead jobs can be retried")
    return {"ok": True}


@router.post("/{job_id}/dismiss")
async def dismiss(job_id: int, db: DB) -> dict[str, bool]:
    """Remove a failed or dead job from the list without running it again.

    The job is marked cancelled (kept briefly for the record, then deleted by retention); it
    never sends anything, so dismissing an unconfirmed delivery cannot duplicate a message.
    """
    job = await db.get(Job, job_id)
    if job is None or job.status not in ("failed", "dead"):
        raise HTTPException(status_code=409, detail="Only failed or dead jobs can be dismissed")
    job.status = "cancelled"
    await db.commit()
    return {"ok": True}
