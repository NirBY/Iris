"""/api/instances: CRUD for the kids' WhatsApp numbers. API keys are write-only."""

import hashlib
import hmac
import secrets
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.models import Instance
from app.deps import get_db
from app.openwa.client import OpenWAClient, OpenWAError
from app.security.auth import current_user
from app.security.crypto import decrypt, encrypt

router = APIRouter(
    prefix="/api/instances", tags=["instances"], dependencies=[Depends(current_user)]
)

DB = Annotated[AsyncSession, Depends(get_db)]
Cfg = Annotated[Settings, Depends(get_settings)]


def webhook_secret(settings: Settings, token: str) -> str:
    """Per-instance HMAC secret for OpenWA's X-OpenWA-Signature, derived (not stored)."""
    return hmac.new(settings.key_bytes, b"webhook:" + token.encode(), hashlib.sha256).hexdigest()


class InstanceIn(BaseModel):
    kid_name: str = Field(min_length=1)
    phone_number: str | None = None
    openwa_base_url: str = Field(min_length=1)
    openwa_instance_id: str = Field(min_length=1)
    openwa_api_key: str | None = None
    enabled: bool = True


class InstancePatch(BaseModel):
    kid_name: str | None = Field(default=None, min_length=1)
    phone_number: str | None = None
    openwa_base_url: str | None = None
    openwa_instance_id: str | None = None
    openwa_api_key: str | None = None
    enabled: bool | None = None


class InstanceOut(BaseModel):
    id: int
    kid_name: str
    phone_number: str | None
    openwa_base_url: str
    openwa_instance_id: str
    api_key_set: bool
    enabled: bool
    webhook_url: str
    last_webhook_at: datetime | None
    created_at: datetime


def to_out(i: Instance, settings: Settings) -> InstanceOut:
    return InstanceOut(
        id=i.id,
        kid_name=i.kid_name,
        phone_number=i.phone_number,
        openwa_base_url=i.openwa_base_url,
        openwa_instance_id=i.openwa_instance_id,
        api_key_set=bool(i.openwa_api_key_enc),
        enabled=i.enabled,
        webhook_url=f"{settings.public_base_url}/webhooks/{i.webhook_token}",
        last_webhook_at=i.last_webhook_at,
        created_at=i.created_at,
    )


async def _get(db: AsyncSession, instance_id: int) -> Instance:
    inst = await db.get(Instance, instance_id)
    if inst is None:
        raise HTTPException(status_code=404, detail="Instance not found")
    return inst


@router.get("")
async def list_instances(db: DB, settings: Cfg) -> list[InstanceOut]:
    rows = (await db.execute(select(Instance).order_by(Instance.id))).scalars().all()
    return [to_out(i, settings) for i in rows]


@router.post("", status_code=201)
async def create_instance(body: InstanceIn, db: DB, settings: Cfg) -> InstanceOut:
    inst = Instance(
        kid_name=body.kid_name,
        phone_number=body.phone_number,
        openwa_base_url=body.openwa_base_url.rstrip("/"),
        openwa_instance_id=body.openwa_instance_id,
        openwa_api_key_enc=encrypt(settings.key_bytes, body.openwa_api_key)
        if body.openwa_api_key
        else None,
        webhook_token=secrets.token_urlsafe(32),
        enabled=body.enabled,
    )
    db.add(inst)
    await db.commit()
    return to_out(inst, settings)


@router.get("/{instance_id}")
async def get_instance(instance_id: int, db: DB, settings: Cfg) -> InstanceOut:
    return to_out(await _get(db, instance_id), settings)


@router.patch("/{instance_id}")
async def update_instance(
    instance_id: int, body: InstancePatch, db: DB, settings: Cfg
) -> InstanceOut:
    inst = await _get(db, instance_id)
    data = body.model_dump(exclude_unset=True)
    key = data.pop("openwa_api_key", None)
    if key:  # empty/absent means "leave unchanged": secrets are write-only in the API
        inst.openwa_api_key_enc = encrypt(settings.key_bytes, key)
    if "openwa_base_url" in data and data["openwa_base_url"]:
        data["openwa_base_url"] = data["openwa_base_url"].rstrip("/")
    for field, value in data.items():
        if value is not None or field == "phone_number":
            setattr(inst, field, value)
    await db.commit()
    return to_out(inst, settings)


@router.delete("/{instance_id}", status_code=204)
async def delete_instance(instance_id: int, db: DB) -> None:
    await db.delete(await _get(db, instance_id))
    await db.commit()


@router.post("/{instance_id}/rotate-token")
async def rotate_token(instance_id: int, db: DB, settings: Cfg) -> InstanceOut:
    inst = await _get(db, instance_id)
    inst.webhook_token = secrets.token_urlsafe(32)  # the old URL stops working immediately
    await db.commit()
    return to_out(inst, settings)


@router.post("/{instance_id}/register-webhook")
async def register_webhook(instance_id: int, db: DB, settings: Cfg) -> dict[str, str]:
    inst = await _get(db, instance_id)
    if not inst.openwa_api_key_enc:
        raise HTTPException(status_code=422, detail="OpenWA API key is not set")
    client = OpenWAClient(
        inst.openwa_base_url, decrypt(settings.key_bytes, inst.openwa_api_key_enc)
    )
    try:
        webhook_id = await client.register_webhook(
            inst.openwa_instance_id,
            f"{settings.public_base_url}/webhooks/{inst.webhook_token}",
            webhook_secret(settings, inst.webhook_token),
        )
    except OpenWAError as exc:
        hint = ""
        if exc.status == 400 and "not allowed" in exc.message.lower():
            hint = (
                " (OpenWA blocks private-network webhook targets: expose Iris on a public hostname)"
            )
        raise HTTPException(status_code=502, detail=f"OpenWA: {exc.message}{hint}") from exc
    finally:
        await client.aclose()
    return {"webhook_id": webhook_id}
