"""deliver_alert job: send one alert over WhatsApp via the configured sender instance."""

import asyncio
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from loguru import logger
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.alerts.format import AlertFacts, MediaFact, format_alert, format_change_notice
from app.alerts.recipients import recipients
from app.config import get_settings
from app.db.models import Alert, Chat, Instance, Job, Message, StoredMedia
from app.jobs.queue import ClaimedJob, PermanentError, TransientError
from app.media.records import stored_for
from app.metrics import ALERTS
from app.openwa.client import OpenWAClient, OpenWAError
from app.security.crypto import decrypt
from app.settings_store import get_setting

if TYPE_CHECKING:
    from app.jobs.handlers import Deps


def recipient_chat_id(recipient: str) -> str:
    """A phone number (digits, optional +) becomes `<digits>@c.us`; chat ids pass through."""
    r = recipient.strip()
    return r if "@" in r else f"{r.lstrip('+')}@c.us"


def _top(alert: Alert) -> str:
    return alert.categories[0] if alert.categories else "unknown"


def _naive_utc(dt: datetime) -> datetime:
    return dt.astimezone(UTC).replace(tzinfo=None) if dt.tzinfo else dt


def _chat_alerts(chat_id: int, alert_id: int) -> "Select[Any]":
    """Other alerts in the same chat."""
    return (
        select(Alert)
        .join(Message, Message.id == Alert.message_id)
        .where(Message.chat_id == chat_id, Alert.id != alert_id)
    )


def build_facts(
    alert: Alert,
    message: Message,
    chat: Chat | None,
    more_suppressed: int = 0,
    media: StoredMedia | None = None,
) -> AlertFacts:
    return AlertFacts(
        alert_id=alert.id,
        kid_names=list(alert.kid_names),
        chat_name=alert.chat_name,
        is_group=bool(chat and chat.is_group),
        sender_name=alert.sender_name,
        from_me=message.from_me,
        categories=list(alert.categories) or ["?"],
        max_score=alert.max_score,
        sent_at=message.sent_at,
        quote=alert.quote,
        more_suppressed=more_suppressed,
        media=(
            MediaFact(media.id, media.kind, media.size_bytes)
            if media is not None and not message.redacted
            else None
        ),
    )


# One process, one delivery decision at a time: the cooldown check and the send must not
# interleave across workers, or two alerts in one chat would both go out.
_DELIVERY_LOCK = asyncio.Lock()


async def send_to_parents(
    db: AsyncSession,
    job: ClaimedJob,
    sender: Instance,
    key_bytes: bytes,
    text: str,
    recipient: str,
) -> None:
    """Persist each successful recipient so retries skip parents already notified."""
    if not sender.openwa_api_key_enc:
        raise PermanentError("alert sender API key is not configured")
    stored = await db.get(Job, job.id)
    payload = dict(stored.payload if stored is not None else job.payload)
    try:
        targets = payload.get("recipients") or recipients(recipient)
    except ValueError:
        raise PermanentError("invalid alert recipient configuration") from None
    completed = list(payload.get("delivered_recipients", []))
    payload["recipients"] = targets
    if stored is not None:
        stored.payload = dict(payload)
        await db.commit()
    client = OpenWAClient(sender.openwa_base_url, decrypt(key_bytes, sender.openwa_api_key_enc))
    errors: list[OpenWAError] = []
    try:
        for target in targets:
            if target in completed:
                continue
            try:
                await client.send_text(sender.openwa_instance_id, target, text)
            except OpenWAError as exc:
                errors.append(exc)
                continue  # one parent's failure must not prevent delivery to another
            completed.append(target)
            payload["delivered_recipients"] = list(completed)
            job.payload.update(payload)
            if stored is not None:
                stored.payload = dict(payload)
                if get_settings().local_safety_mode and job.type == "deliver_alert":
                    alert = await db.get(Alert, payload.get("alert_id"))
                    if alert is not None:
                        alert.delivery_status = "partial"
                        alert.notified_at = alert.notified_at or datetime.now(UTC)
                await db.commit()
    finally:
        await client.aclose()
    if errors:
        detail = (
            f"alert delivery failed for {len(errors)} of {len(targets)} recipients: "
            + "; ".join(
                f"provider status {e.status or 'unavailable'}"
                if get_settings().local_safety_mode
                else e.message[:100]
                for e in errors
            )
        )
        if any(e.status is None or e.status >= 500 or e.status == 429 for e in errors):
            raise TransientError(detail)
        raise PermanentError(detail)


async def deliver_alert(job: ClaimedJob, deps: "Deps") -> None:
    async with _DELIVERY_LOCK:
        await _deliver(job, deps)


async def _deliver(job: ClaimedJob, deps: "Deps") -> None:
    alert_id = job.payload.get("alert_id")
    force = bool(job.payload.get("force"))  # manual resend ignores the cooldown
    if not isinstance(alert_id, int):
        raise PermanentError("job payload has no alert_id")
    async with deps.session_factory() as db:
        alert = await db.get(Alert, alert_id)
        if alert is None:
            raise PermanentError("alert no longer exists")
        if alert.delivery_status == "sent" and not force:
            return
        message = await db.get(Message, alert.message_id)
        if message is None:
            raise PermanentError("alert's message no longer exists")
        chat = await db.get(Chat, message.chat_id)

        sender_id = await get_setting(db, "alerts.sender_instance_id")
        recipient = await get_setting(db, "alerts.recipient")
        sender = await db.get(Instance, sender_id) if sender_id else None
        if not recipient or sender is None or not sender.openwa_api_key_enc:
            alert.delivery_status, alert.delivery_error = "failed", "alert delivery not configured"
            await db.commit()
            raise PermanentError("alert delivery not configured")

        more = 0
        last_sent = (
            await db.scalars(
                _chat_alerts(message.chat_id, alert.id)
                .where(Alert.notified_at.is_not(None))
                .order_by(Alert.notified_at.desc())
                .limit(1)
            )
        ).first()
        if last_sent is not None and last_sent.notified_at is not None:
            cooldown = int(await get_setting(db, "alerts.cooldown_minutes"))
            window_start = _naive_utc(datetime.now(UTC)) - timedelta(minutes=cooldown)
            if (
                not force
                and not job.payload.get("delivered_recipients")
                and _naive_utc(last_sent.notified_at) >= window_start
            ):
                alert.delivery_status, alert.delivery_error = "suppressed", None
                await db.commit()
                ALERTS.labels(_top(alert), "suppressed").inc()
                logger.info("alert {} suppressed by the chat cooldown", alert.id)
                return
            more = int(
                (
                    await db.execute(
                        select(func.count())
                        .select_from(Alert)
                        .join(Message, Message.id == Alert.message_id)
                        .where(
                            Message.chat_id == message.chat_id,
                            Alert.id != alert.id,
                            Alert.delivery_status == "suppressed",
                            Alert.created_at > last_sent.notified_at,
                        )
                    )
                ).scalar_one()
            )

        timezone = str(await get_setting(db, "alerts.timezone"))
        facts = build_facts(
            alert, message, chat, more_suppressed=more, media=await stored_for(db, message.id)
        )
        text = format_alert(facts, timezone, deps.public_base_url, deps.key_bytes)
        try:
            await send_to_parents(db, job, sender, deps.key_bytes, text, recipient)
        except PermanentError as exc:
            partial = get_settings().local_safety_mode and job.payload.get("delivered_recipients")
            alert.delivery_status = "partial" if partial else "failed"
            alert.delivery_error = str(exc)[:300]
            await db.commit()
            raise
        alert.delivery_status, alert.delivery_error = "sent", None
        alert.notified_at = datetime.now(UTC)
        await db.commit()
        ALERTS.labels(_top(alert), "sent").inc()
        logger.info("alert {} delivered", alert.id)


async def notify_change(job: ClaimedJob, deps: "Deps") -> None:
    """Tell the parent that the message of an already delivered alert was edited or deleted."""
    alert_id, kind = job.payload.get("alert_id"), job.payload.get("kind")
    if not isinstance(alert_id, int) or kind not in ("edited", "revoked"):
        raise PermanentError("job payload has no alert_id or kind")
    async with _DELIVERY_LOCK, deps.session_factory() as db:
        alert = await db.get(Alert, alert_id)
        if alert is None:
            raise PermanentError("alert no longer exists")
        if alert.delivery_status == "pending":
            raise TransientError("the alert itself is not delivered yet")
        if alert.delivery_status not in ("sent", "partial"):
            logger.info("alert {} never reached the parent; no follow-up", alert.id)
            return
        message = await db.get(Message, alert.message_id)
        if message is None:
            raise PermanentError("alert's message no longer exists")
        chat = await db.get(Chat, message.chat_id)
        sender_id = await get_setting(db, "alerts.sender_instance_id")
        recipient = await get_setting(db, "alerts.recipient")
        sender = await db.get(Instance, sender_id) if sender_id else None
        if not recipient or sender is None or not sender.openwa_api_key_enc:
            raise PermanentError("alert delivery not configured")
        timezone = str(await get_setting(db, "alerts.timezone"))
        text = format_change_notice(
            kind, build_facts(alert, message, chat), timezone, deps.public_base_url, deps.key_bytes
        )
        if alert.delivery_status == "partial":
            original = (
                await db.scalars(
                    select(Job)
                    .where(
                        Job.type == "deliver_alert",
                        Job.payload["alert_id"].as_integer() == alert.id,
                    )
                    .order_by(Job.id.desc())
                )
            ).first()
            delivered = original.payload.get("delivered_recipients", []) if original else []
            if not delivered:
                return
            job.payload["recipients"] = delivered
            stored = await db.get(Job, job.id)
            if stored is not None:
                stored.payload = dict(job.payload)
                await db.commit()
        await send_to_parents(db, job, sender, deps.key_bytes, text, recipient)
        logger.info("alert {} follow-up ({}) delivered", alert.id, kind)
