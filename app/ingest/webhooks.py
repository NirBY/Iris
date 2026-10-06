"""POST /webhooks/{token}: validate, normalize, store, enqueue, return 200 fast.

Never calls external APIs: all slow work happens in the job workers.
"""

import hashlib
import hmac
import json
import re
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from loguru import logger
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.alerts import ALERT_PREFIX
from app.api.instances import webhook_secret
from app.config import Settings, get_settings
from app.db.models import Chat, ChatInstance, Instance, Job, Message, MessageReceipt
from app.deps import get_db
from app.openwa.payloads import IncomingMessage, PayloadError, parse_event
from app.settings_store import get_setting

router = APIRouter()

# Media is normally referenced, but OpenWA inlines small files as base64.
MAX_BODY_BYTES = 25 * 1024 * 1024
_ID_RE = re.compile(r"^(\d+)")


def _id_digits(wa_id: str | None) -> str | None:
    """Digits of a WhatsApp id (`972...@c.us`, `1234@lid`, `1234:59@lid`) or a bare phone."""
    m = _ID_RE.match((wa_id or "").lstrip("+").strip())
    return m.group(1) if m else None


async def _is_alert_loop(db: AsyncSession, inst: Instance, msg: IncomingMessage) -> bool:
    """Skip Iris's own alerts so they are never classified (and never alert again)."""
    sender_id = await get_setting(db, "alerts.sender_instance_id")
    if sender_id != inst.id:
        return False
    if msg.from_me and (msg.text or "").startswith(ALERT_PREFIX):
        return True
    recipient = _id_digits(await get_setting(db, "alerts.recipient"))
    return recipient is not None and recipient == _id_digits(msg.wa_chat_id)


async def _in_scope(db: AsyncSession, msg: IncomingMessage) -> bool:
    if msg.from_me and not await get_setting(db, "scope.monitor_from_me"):
        return False
    key = "scope.monitor_groups" if msg.is_group else "scope.monitor_direct"
    return bool(await get_setting(db, key))


async def _store(db: AsyncSession, inst: Instance, msg: IncomingMessage) -> str:
    chat = (
        await db.execute(select(Chat).where(Chat.wa_chat_id == msg.wa_chat_id))
    ).scalar_one_or_none()
    if chat is None:
        chat = Chat(wa_chat_id=msg.wa_chat_id, is_group=msg.is_group)
        db.add(chat)
        await db.flush()
    if chat.name is None and not msg.is_group and not msg.from_me:
        chat.name = msg.sender_name  # direct chat: named after the other party
    if await db.get(ChatInstance, (chat.id, inst.id)) is None:
        db.add(ChatInstance(chat_id=chat.id, instance_id=inst.id))

    existing = (
        await db.execute(
            select(Message).where(
                Message.chat_id == chat.id, Message.wa_message_id == msg.wa_message_id
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        if await db.get(MessageReceipt, (existing.id, inst.id)) is None:
            db.add(MessageReceipt(message_id=existing.id, instance_id=inst.id))
        await db.commit()
        return "duplicate"

    message = Message(
        wa_message_id=msg.wa_message_id,
        chat_id=chat.id,
        sender_wa_id=msg.sender_wa_id,
        sender_name=inst.kid_name if msg.from_me else msg.sender_name,
        from_me=msg.from_me,
        type=msg.type,
        text=msg.text,
        quoted_wa_message_id=msg.quoted_wa_message_id,
        sent_at=msg.sent_at,
        status="pending",
    )
    db.add(message)
    await db.flush()
    db.add(MessageReceipt(message_id=message.id, instance_id=inst.id))
    media: dict[str, Any] | None = None
    if msg.media:
        media = {
            "chat_id": msg.wa_chat_id,
            "message_ref": msg.wa_message_ref,
            "mimetype": msg.media.mimetype,
            "filename": msg.media.filename,
            "size_bytes": msg.media.size_bytes,
        }
    db.add(
        Job(
            type="process_message",
            payload={"message_id": message.id, "instance_id": inst.id, "media": media},
        )
    )
    try:
        await db.commit()
    except IntegrityError:  # a concurrent delivery from another instance won the race
        await db.rollback()
        return await _store(db, inst, msg)
    return "accepted"


@router.post("/webhooks/{token}")
async def receive(
    token: str,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, str]:
    inst = (
        await db.execute(select(Instance).where(Instance.webhook_token == token))
    ).scalar_one_or_none()
    # Unknown or disabled: same 404, so the response never reveals which.
    if inst is None or not hmac.compare_digest(inst.webhook_token, token) or not inst.enabled:
        raise HTTPException(status_code=404)
    logger.debug("webhook for instance {} (token {}...)", inst.id, token[:6])

    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        raise HTTPException(status_code=413)
    raw = await request.body()
    if len(raw) > MAX_BODY_BYTES:
        raise HTTPException(status_code=413)

    sig = request.headers.get("x-openwa-signature")
    if sig is not None:
        expected = (
            "sha256="
            + hmac.new(webhook_secret(settings, token).encode(), raw, hashlib.sha256).hexdigest()
        )
        if not hmac.compare_digest(sig, expected):
            raise HTTPException(status_code=401, detail="bad signature")

    try:
        body = json.loads(raw)
        msg = parse_event(body) if isinstance(body, dict) else None
    except (ValueError, PayloadError) as exc:
        # 200 so OpenWA does not retry a payload we can never parse.
        logger.warning("unparseable webhook for instance {}: {}", inst.id, exc.__class__.__name__)
        return {"result": "rejected"}

    inst.last_webhook_at = datetime.now(UTC)
    if msg is None:
        await db.commit()
        return {"result": "ignored"}
    if await _is_alert_loop(db, inst, msg) or not await _in_scope(db, msg):
        await db.commit()
        return {"result": "skipped"}
    return {"result": await _store(db, inst, msg)}
