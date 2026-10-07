"""Alert creation (spec 9.1) and the sexual-content redaction rule (spec 8.5)."""

from typing import Any

from loguru import logger
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.alerts.format import make_quote
from app.classify.pipeline import PipelineOutcome
from app.classify.thresholds import effective_thresholds
from app.db.models import (
    Alert,
    Chat,
    Classification,
    Instance,
    Message,
    MessageReceipt,
    MessageRevision,
)
from app.jobs.queue import enqueue
from app.media.records import mark_purge
from app.metrics import ALERTS
from app.settings_store import get_setting

REDACTED = "[redacted]"
MEDIA_TYPES = ("image", "sticker", "video")
DELIVERY_JOB = "deliver_alert"
DELIVERY_ATTEMPTS = 3


def should_redact(message_type: str, categories: list[str]) -> bool:
    """Sexual content involving minors, or sexual imagery: never stored, never forwarded."""
    return "sexual/minors" in categories or (message_type in MEDIA_TYPES and "sexual" in categories)


def needs_redaction(message_type: str, high: list[str], low: list[str]) -> bool:
    """Decide at classification time, before anything is shown or alerted.

    `sexual/minors` at or above its high threshold is withheld. In the uncertain band (above low,
    below high) the words of a TEXT or voice message are kept so the owner can read them in the
    review queue and decide (they are withheld the moment it is confirmed harmful); anything with
    a picture (image, sticker, video) is withheld at any band. Sexual imagery is withheld at the
    high threshold, as in the spec.
    """
    if "sexual/minors" in high:
        return True
    if "sexual/minors" in low and message_type in MEDIA_TYPES:
        return True
    return should_redact(message_type, high)


def redact_for_alert(
    message_type: str,
    scores: dict[str, float],
    thresholds: dict[str, tuple[float, float]],
    confirmed: bool = False,
) -> bool:
    """The same decision when an alert is created (the scores are what triggered it).

    `confirmed` is true when the owner has just marked the message harmful: an item kept for
    review is then withheld.
    """
    minors = scores.get("sexual/minors")
    if minors is not None and (
        confirmed
        or message_type in MEDIA_TYPES
        or minors >= thresholds.get("sexual/minors", (0.05, 0.30))[1]
    ):
        return True
    return message_type in MEDIA_TYPES and "sexual" in scores


def redact_message(message: Message) -> None:
    """Withhold the content: row keeps metadata only; FTS blanks itself via the update trigger."""
    message.text = REDACTED
    message.transcript = REDACTED
    message.media = None  # no way back to the attachment (reprocess is blocked anyway)
    message.redacted = True


async def wipe_revisions(db: AsyncSession, message_id: int) -> None:
    """Withheld content must not survive in the edit history either."""
    await db.execute(delete(MessageRevision).where(MessageRevision.message_id == message_id))


async def _kid_names(db: AsyncSession, message_id: int) -> list[str]:
    rows = await db.execute(
        select(Instance.kid_name)
        .join(MessageReceipt, MessageReceipt.instance_id == Instance.id)
        .where(MessageReceipt.message_id == message_id)
        .order_by(Instance.id)
    )
    return list(rows.scalars())


async def delivery_configured(db: AsyncSession) -> bool:
    return bool(
        await get_setting(db, "alerts.sender_instance_id")
        and await get_setting(db, "alerts.recipient")
    )


async def create_alert(
    db: AsyncSession, message: Message, scores: dict[str, float], confirmed: bool = False
) -> Alert:
    """Create the alert for a message (one per message) and queue its delivery.

    `scores` maps the triggering categories to their scores. Redaction and the alert row are
    committed together, so withheld content can never be quoted by a half-finished alert.
    """
    existing = (
        await db.execute(select(Alert).where(Alert.message_id == message.id))
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    ordered = sorted((scores or {"manual review": 0.0}).items(), key=lambda kv: kv[1], reverse=True)
    categories = [c for c, _ in ordered]
    chat = await db.get(Chat, message.chat_id)
    thresholds = effective_thresholds(await get_setting(db, "classification.thresholds"))
    redact = message.redacted or redact_for_alert(message.type, scores, thresholds, confirmed)
    if redact:
        redact_message(message)
        await wipe_revisions(db, message.id)
        await mark_purge(db, message.id)
        quote = None
        logger.warning("message {} redacted ({}); content withheld", message.id, categories)
    else:
        quote = make_quote(message.type, message.text, message.transcript)

    alert = Alert(
        message_id=message.id,
        categories=categories,
        max_score=ordered[0][1] if ordered else 0.0,
        kid_names=await _kid_names(db, message.id),
        chat_name=chat.name if chat else None,
        sender_name=message.sender_name,
        quote=quote,
        status="new",
        delivery_status="pending",
    )
    db.add(alert)
    await db.flush()
    if await delivery_configured(db):
        await enqueue(db, DELIVERY_JOB, {"alert_id": alert.id}, max_attempts=DELIVERY_ATTEMPTS)
    else:
        alert.delivery_status = "failed"
        alert.delivery_error = "alert delivery not configured"
        ALERTS.labels(categories[0], "failed").inc()
    await db.commit()
    return alert


def outcome_scores(outcome: PipelineOutcome) -> dict[str, float]:
    """Triggering categories (and scores) of the stage that decided the verdict."""
    final = outcome.results[-1].scores if outcome.results else {}
    return {c: float(final[c]) for c in outcome.categories if c in final}


async def scores_from_classifications(db: AsyncSession, message: Message) -> dict[str, float]:
    """For a manual 'harmful' from the review queue: the categories at or above their low
    threshold in the latest classification (the message was inconclusive, so none reached high)."""
    last = (
        await db.execute(
            select(Classification)
            .where(Classification.message_id == message.id)
            .order_by(Classification.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if last is None:
        return {}
    scores: dict[str, Any] = last.scores
    return {c: float(scores[c]) for c in last.flagged_categories if c in scores}


async def alert_on_harmful(db: AsyncSession, message: Message, outcome: PipelineOutcome) -> None:
    await create_alert(db, message, outcome_scores(outcome))


async def alert_on_review(db: AsyncSession, message: Message, outcome: PipelineOutcome) -> None:
    """Review items alert only when the parent opted in (alerts.alert_on_review)."""
    if not await get_setting(db, "alerts.alert_on_review"):
        return
    last = outcome.results[-1] if outcome.results else None
    if last is None:
        return
    scores = {c: float(last.scores[c]) for c in last.flagged_categories if c in last.scores}
    await create_alert(db, message, scores)
