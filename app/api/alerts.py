"""/api/alerts and /api/review: alert list/detail/actions and the review queue."""

from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import ColumnElement, and_, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.alerts.service import (
    DELIVERY_ATTEMPTS,
    DELIVERY_JOB,
    create_alert,
    delivery_configured,
    flagged_union,
    redact_for_alert,
    scores_from_classifications,
)
from app.api.media import MediaOut, media_out
from app.api.messages import (
    ClassificationOut,
    MessageOut,
    _failures,
    _kids,
    _load,
    _to_out,
)
from app.classify.thresholds import effective_thresholds
from app.config import Settings, get_settings
from app.db.jsonq import json_array_contains
from app.db.models import (
    Alert,
    Classification,
    Job,
    Message,
    MessageReceipt,
    ReviewDataIssue,
    ReviewFeedback,
    StoredMedia,
)
from app.deps import get_db
from app.jobs.queue import enqueue
from app.media.keep import keep_media, wants
from app.media.records import mark_purge
from app.security.auth import current_user, parent_user
from app.settings_store import get_setting

router = APIRouter(prefix="/api", tags=["alerts"], dependencies=[Depends(current_user)])
DB = Annotated[AsyncSession, Depends(get_db)]


class AlertOut(BaseModel):
    verdict: str | None = None
    review_reason: str | None = None
    id: int
    message_id: int
    chat_id: int
    categories: list[str]
    max_score: float
    kid_names: list[str]
    chat_name: str | None
    sender_name: str | None
    quote: str | None
    redacted: bool  # content withheld (spec 8.5): the alert carries metadata only
    status: str
    delivery_status: str
    delivery_error: str | None
    notified_at: datetime | None
    created_at: datetime
    edited_at: datetime | None  # the message was edited after the alert
    revoked_at: datetime | None  # the sender deleted it for everyone
    media: MediaOut | None = None  # a kept copy of the message's media, when there is one


class AlertDetail(AlertOut):
    message_type: str
    sent_at: datetime
    classifications: list[ClassificationOut]
    recipient_delivery: list[dict[str, str]] = []


class AlertPage(BaseModel):
    items: list[AlertOut]
    total: int
    page: int
    page_size: int


def _out(a: Alert, m: Message, media: StoredMedia | None = None) -> AlertOut:
    return AlertOut(
        id=a.id,
        verdict=m.verdict,
        review_reason=m.review_reason,
        message_id=a.message_id,
        chat_id=m.chat_id,
        categories=list(a.categories),
        max_score=a.max_score,
        kid_names=list(a.kid_names),
        chat_name=a.chat_name,
        sender_name=a.sender_name,
        quote=None if m.redacted else a.quote,
        redacted=m.redacted,
        status=a.status,
        delivery_status=a.delivery_status,
        delivery_error=a.delivery_error,
        edited_at=m.edited_at,
        revoked_at=m.revoked_at,
        notified_at=a.notified_at,
        created_at=a.created_at,
        media=media_out(media) if media is not None and not m.redacted else None,
    )


async def _media_by_message(db: AsyncSession, message_ids: list[int]) -> dict[int, StoredMedia]:
    """The shown copy for each message (one query for a whole page of alerts)."""
    if not message_ids:
        return {}
    rows = await db.execute(
        select(StoredMedia)
        .where(StoredMedia.message_id.in_(message_ids), StoredMedia.purge.is_(False))
        .order_by(StoredMedia.id.desc())
    )
    return {r.message_id: r for r in rows.scalars()}


@router.get("/alerts")
async def list_alerts(
    db: DB,
    status: str | None = None,
    delivery_status: str | None = None,
    instance_id: int | None = None,
    chat_id: int | None = None,
    category: str | None = None,
    from_: Annotated[datetime | None, Query(alias="from")] = None,
    to: datetime | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
) -> AlertPage:
    conds: list[ColumnElement[bool]] = []
    if status:
        conds.append(Alert.status == status)
    if delivery_status:
        conds.append(Alert.delivery_status == delivery_status)
    if instance_id is not None:
        conds.append(
            exists().where(
                MessageReceipt.message_id == Alert.message_id,
                MessageReceipt.instance_id == instance_id,
            )
        )
    if chat_id is not None:
        conds.append(Message.chat_id == chat_id)
    if category:
        conds.append(json_array_contains(Alert.categories, category))
    if from_:
        conds.append(Alert.created_at >= from_)
    if to:
        conds.append(Alert.created_at <= to)
    where = and_(*conds) if conds else None
    base = select(Alert, Message).join(Message, Message.id == Alert.message_id)
    count = select(func.count()).select_from(Alert).join(Message, Message.id == Alert.message_id)
    if where is not None:
        base, count = base.where(where), count.where(where)
    total = int((await db.execute(count)).scalar_one())
    rows = (
        await db.execute(
            base.order_by(Alert.created_at.desc(), Alert.id.desc())
            .limit(page_size)
            .offset((page - 1) * page_size)
        )
    ).all()
    media = await _media_by_message(db, [m.id for _, m in rows])
    return AlertPage(
        items=[_out(a, m, media.get(m.id)) for a, m in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


async def _alert(db: AsyncSession, alert_id: int) -> tuple[Alert, Message]:
    row = (
        await db.execute(
            select(Alert, Message)
            .join(Message, Message.id == Alert.message_id)
            .where(Alert.id == alert_id)
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    return row[0], row[1]


@router.get("/alerts/{alert_id}")
async def get_alert(alert_id: int, db: DB) -> AlertDetail:
    a, m = await _alert(db, alert_id)
    cls = (
        await db.execute(
            select(Classification)
            .where(Classification.message_id == m.id)
            .order_by(Classification.id)
        )
    ).scalars()
    latest = await db.scalar(
        select(Job)
        .where(Job.type == DELIVERY_JOB, Job.payload["alert_id"].as_integer() == alert_id)
        .order_by(Job.id.desc())
        .limit(1)
    )
    deliveries = []
    if latest is not None:
        payload = latest.payload
        for target in payload.get("recipients", []):
            status = (
                "delivered"
                if target in payload.get("delivered_recipients", [])
                else "uncertain"
                if target in payload.get("uncertain_recipients", [])
                else "rejected"
                if target in payload.get("rejected_recipients", {})
                else "not sent"
                if latest.status == "failed"
                else "pending"
            )
            label = (
                "Email " + target.removeprefix("email:").split("@")[0][:1] + "…"
                if target.startswith("email:")
                else "Recipient ending " + target.split("@")[0][-4:]
            )
            deliveries.append({"recipient": label, "status": status})
    return AlertDetail(
        **_out(a, m, (await _media_by_message(db, [m.id])).get(m.id)).model_dump(),
        recipient_delivery=deliveries,
        message_type=m.type,
        sent_at=m.sent_at,
        classifications=[ClassificationOut.model_validate(c, from_attributes=True) for c in cls],
    )


class AlertPatch(BaseModel):
    status: Literal["new", "acknowledged", "dismissed"]


@router.patch("/alerts/{alert_id}", dependencies=[Depends(parent_user)])
async def patch_alert(alert_id: int, body: AlertPatch, db: DB) -> AlertOut:
    a, m = await _alert(db, alert_id)
    a.status = body.status
    await db.commit()
    return _out(a, m, (await _media_by_message(db, [m.id])).get(m.id))


@router.post("/alerts/{alert_id}/resend", dependencies=[Depends(parent_user)])
async def resend_alert(alert_id: int, db: DB) -> dict[str, bool]:
    a, _ = await _alert(db, alert_id)
    if not await delivery_configured(db):
        raise HTTPException(status_code=422, detail="Alert delivery is not configured")
    if await _delivery_active(db, a.id):
        raise HTTPException(status_code=409, detail="Delivery already in progress")
    payload = {"alert_id": a.id, "force": True}
    if a.delivery_status in ("partial", "failed"):
        previous = await db.scalar(
            select(Job)
            .where(Job.type == DELIVERY_JOB, Job.payload["alert_id"].as_integer() == a.id)
            .order_by(Job.id.desc())
            .limit(1)
        )
        if previous is not None:
            payload = {**previous.payload, **payload}
            for key in ("delivery_uncertain", "uncertain_recipients", "rejected_recipients"):
                payload.pop(key, None)
    a.delivery_status, a.delivery_error = "pending", None
    await enqueue(db, DELIVERY_JOB, payload, max_attempts=DELIVERY_ATTEMPTS)
    return {"ok": True}


async def _delivery_active(db: AsyncSession, alert_id: int) -> bool:
    from app.db.models import Job

    n = (
        await db.execute(
            select(func.count())
            .select_from(Job)
            .where(
                Job.type == DELIVERY_JOB,
                Job.status.in_(["queued", "running"]),
                Job.payload["alert_id"].as_integer() == alert_id,
            )
        )
    ).scalar_one()
    return int(n) > 0


# --- review queue -------------------------------------------------------------------------------


class ReviewItem(BaseModel):
    missing_data: bool = False
    message: MessageOut
    classifications: list[ClassificationOut]


class ReviewPage(BaseModel):
    reviewed_total: int = 0
    items: list[ReviewItem]
    total: int
    page: int
    page_size: int


@router.get("/review")
async def review_queue(
    db: DB,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
    view: Literal["pending", "missing_data"] = "pending",
) -> ReviewPage:
    from app.db.models import Chat

    reported = exists().where(ReviewDataIssue.message_id == Message.id)
    cond = and_(Message.verdict == "review", reported if view == "missing_data" else ~reported)
    total = int(
        (await db.execute(select(func.count()).select_from(Message).where(cond))).scalar_one()
    )
    rows = (
        await db.execute(
            select(Message, Chat)
            .join(Chat, Chat.id == Message.chat_id)
            .where(cond)
            .order_by(Message.sent_at.desc(), Message.id.desc())
            .limit(page_size)
            .offset((page - 1) * page_size)
        )
    ).all()
    kids = await _kids(db, [m.id for m, _ in rows])
    failures = await _failures(db, [m for m, _ in rows])
    items: list[ReviewItem] = []
    for m, c in rows:
        cls = (
            await db.execute(
                select(Classification)
                .where(Classification.message_id == m.id)
                .order_by(Classification.id)
            )
        ).scalars()
        items.append(
            ReviewItem(
                missing_data=view == "missing_data",
                message=_to_out(m, c, kids.get(m.id, []), failure=failures.get(m.id)),
                classifications=[
                    ClassificationOut.model_validate(x, from_attributes=True) for x in cls
                ],
            )
        )
    return ReviewPage(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        reviewed_total=int(
            (
                await db.execute(
                    select(func.count())
                    .select_from(ReviewFeedback)
                    .where(ReviewFeedback.verdict.in_(("safe", "harmful")))
                )
            ).scalar_one()
        ),
    )


class ReviewResolution(BaseModel):
    resolution: Literal["safe", "harmful"]


@router.post("/review/{message_id}", dependencies=[Depends(parent_user)])
async def resolve_review(
    message_id: int,
    body: ReviewResolution,
    request: Request,
    db: DB,
    cfg: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    m, _ = await _load(db, message_id)
    if m.verdict != "review":
        raise HTTPException(status_code=409, detail="Message is not awaiting review")
    m.verdict = body.resolution
    m.review_reason = None
    # Separate human labels from original scores/categories used to build alerts.
    feedback = await db.get(ReviewFeedback, m.id)
    if feedback:
        feedback.verdict = body.resolution
        feedback.reviewed_at = datetime.now(UTC)
    else:
        db.add(ReviewFeedback(message_id=m.id, verdict=body.resolution))
    alert_id: int | None = None
    policy = str(await get_setting(db, "media.policy"))
    if body.resolution == "harmful":
        scores = await scores_from_classifications(db, m)
        thresholds = effective_thresholds(await get_setting(db, "classification.thresholds"))
        flags = await flagged_union(db, m.id)
        if redact_for_alert(m.type, {**{c: 0.0 for c in flags}, **scores}, thresholds, True):
            # Withheld content: the verdict and the redaction commit together, with nothing kept.
            alert = await create_alert(db, m, scores, confirmed=True)
        else:
            await db.commit()
            # Before the alert is built, so its text carries the link (best effort, never fails).
            await keep_media(
                request.app.state.session_factory,
                m.id,
                list(scores),
                cfg.key_bytes,
                cfg.data_dir,
                f"review-{m.id}",
            )
            await db.refresh(m)  # the other session may have flagged or changed it meanwhile
            alert = await create_alert(db, m, scores, confirmed=True)
        alert_id = alert.id
    else:
        if not wants(policy, "safe"):
            await mark_purge(db, m.id)  # kept only because it was awaiting review
        await db.commit()
    return {"ok": True, "verdict": body.resolution, "alert_id": alert_id}


class ReviewDataReport(BaseModel):
    issue: Literal["missing_data"]


@router.post("/review/{message_id}/data-issue", dependencies=[Depends(parent_user)])
async def report_review_data(message_id: int, body: ReviewDataReport, db: DB) -> dict[str, Any]:
    message, _ = await _load(db, message_id)
    if message.verdict != "review":
        raise HTTPException(status_code=409, detail="Message is not awaiting review")
    if await db.get(ReviewDataIssue, message_id) is None:
        db.add(ReviewDataIssue(message_id=message_id, issue=body.issue))
        await db.commit()
    return {"ok": True, "ignored": True, "issue": body.issue}
