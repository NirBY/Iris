"""Admin-only account management and tested SMTP / 2FA settings."""

import asyncio
import ipaddress
import json
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import _set_session_cookie
from app.config import Settings, get_settings
from app.db.models import LoginChallenge, Setting, User
from app.deps import get_db
from app.security.auth import admin_user, hash_password
from app.security.crypto import encrypt
from app.security.two_factor import (
    CONFIG_KEY,
    CONTACT_PREFIX,
    ENABLED_KEY,
    GREEN_API_KEY,
    available_channels,
    contact_link,
    email_address,
    green_api_config,
    load,
    reserve_green,
    save,
    send_green_code,
    send_smtp,
    smtp_config,
    whatsapp_number,
)

router = APIRouter(prefix="/api/users", tags=["users"], dependencies=[Depends(admin_user)])
DB = Annotated[AsyncSession, Depends(get_db)]
Cfg = Annotated[Settings, Depends(get_settings)]
Admin = Annotated[User, Depends(admin_user)]


class UserBody(BaseModel):
    username: str = Field(min_length=1, max_length=255, pattern=r"^[^\s]+$")
    role: Literal["admin", "parent", "watch"] = "watch"
    password: str | None = Field(default=None, min_length=8, max_length=256)
    email: str | None = None
    whatsapp_number: str | None = None

    @field_validator("whatsapp_number")
    @classmethod
    def valid_whatsapp(cls, value: str | None) -> str | None:
        return whatsapp_number(value)

    @field_validator("email")
    @classmethod
    def valid_email(cls, value: str | None) -> str | None:
        return email_address(value)


def out(user: User) -> dict[str, Any]:
    return {
        "id": user.id,
        "username": user.username,
        "role": user.role,
        "email": user.email,
        "whatsapp_number": user.whatsapp_number,
        "email_verified": user.email_verified,
        "whatsapp_verified": user.whatsapp_verified,
    }


async def validate_contacts(db: AsyncSession, user: User, enabled: bool, cfg: Settings) -> None:
    if enabled and not await available_channels(db, cfg, user):
        raise HTTPException(
            422,
            f"{user.username} needs an approved email or WhatsApp number with a tested provider",
        )


async def validate_enrollment_contact(db: AsyncSession, user: User, cfg: Settings) -> None:
    """A new account needs a deliverable contact; approval follows account creation."""
    smtp = await smtp_config(db, cfg)
    green = await green_api_config(db, cfg)
    if not (
        (user.email and smtp.get("verified")) or (user.whatsapp_number and green.get("verified"))
    ):
        raise HTTPException(
            422,
            "2FA is enabled: configure an email or WhatsApp number with a tested provider, "
            "then approve the contact before login",
        )


async def unique_contacts(db: AsyncSession, body: UserBody, user_id: int | None = None) -> None:
    for column, value, label in (
        (
            func.lower(func.trim(User.email)),
            body.email.strip().lower() if body.email else None,
            "Email",
        ),
        (User.whatsapp_number, body.whatsapp_number, "WhatsApp number"),
    ):
        if value:
            query = select(User.id).where(column == value)
            if user_id is not None:
                query = query.where(User.id != user_id)
            if await db.scalar(query) is not None:
                raise HTTPException(409, f"{label} is already assigned to another user")


async def commit_user(db: AsyncSession, user: User, body: UserBody) -> None:
    user.email_contact_key = body.email.strip().lower() if body.email else None
    user.whatsapp_contact_key = body.whatsapp_number
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "Email, WhatsApp number or username is already in use") from None


@router.get("")
async def list_users(db: DB) -> list[dict[str, Any]]:
    return [out(user) for user in (await db.execute(select(User).order_by(User.id))).scalars()]


@router.post("", status_code=201)
async def create_user(body: UserBody, db: DB, cfg: Cfg) -> dict[str, Any]:
    if not body.password:
        raise HTTPException(422, "Password is required for a new user")
    if (await db.execute(select(User.id).where(User.username == body.username))).first():
        raise HTTPException(409, "Username is already in use")
    await unique_contacts(db, body)
    user = User(**body.model_dump(exclude={"password"}), password_hash=hash_password(body.password))
    if await load(db, ENABLED_KEY, False):
        await validate_enrollment_contact(db, user, cfg)
    db.add(user)
    await commit_user(db, user, body)
    return out(user)


@router.put("/{user_id}")
async def update_user(
    user_id: int, body: UserBody, db: DB, admin: Admin, cfg: Cfg, response: Response
) -> dict[str, Any]:
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "User not found")
    if user.id == admin.id and body.role != "admin":
        raise HTTPException(422, "You cannot remove your own admin role")
    if (
        await db.execute(select(User.id).where(User.username == body.username, User.id != user_id))
    ).first():
        raise HTTPException(409, "Username is already in use")
    await unique_contacts(db, body, user_id)
    was_ready = bool(await available_channels(db, cfg, user))
    if user.email != body.email:
        user.email_verified = False
    if user.whatsapp_number != body.whatsapp_number:
        user.whatsapp_verified = False
    changed = bool(body.password) or any(
        getattr(user, key) != value for key, value in body.model_dump(exclude={"password"}).items()
    )
    for key, value in body.model_dump(exclude={"password"}).items():
        setattr(user, key, value)
    if body.password:
        user.password_hash = hash_password(body.password)
    if changed:
        user.auth_version += 1
    if await load(db, ENABLED_KEY, False):
        if was_ready:
            await validate_contacts(db, user, True, cfg)
        else:
            await validate_enrollment_contact(db, user, cfg)
    await commit_user(db, user, body)
    if user.id == admin.id:
        _set_session_cookie(response, cfg, user)
    return out(user)


class SMTPBody(BaseModel):
    host: str = Field(min_length=1, max_length=255, pattern=r"^[A-Za-z0-9.\-]+$")
    port: int = Field(default=587, ge=1, le=65535)
    tls: Literal["starttls", "ssl"] = "starttls"
    username: str = Field(min_length=1, max_length=255)
    password: str | None = Field(default=None, max_length=512)
    sender: str

    @field_validator("sender")
    @classmethod
    def valid_sender(cls, value: str) -> str:
        return email_address(value) or ""

    @field_validator("host")
    @classmethod
    def valid_host(cls, value: str) -> str:
        try:
            address = ipaddress.ip_address(value)
        except ValueError:
            return value
        if address.is_link_local or address.is_unspecified or address.is_multicast:
            raise ValueError("SMTP address is not allowed")
        return value


@router.get("/security/config")
async def security_config(db: DB, cfg: Cfg) -> dict[str, Any]:
    config = await smtp_config(db, cfg)
    green = await green_api_config(db, cfg)
    return {
        "green_api": {key: value for key, value in green.items() if key != "token"},
        "green_api_token_set": bool(green.get("token")),
        "smtp": {key: value for key, value in config.items() if key != "password"},
        "password_set": bool(config.get("password")),
        "enabled": bool(await load(db, ENABLED_KEY, False)),
    }


@router.put("/security/smtp")
async def configure_smtp(body: SMTPBody, db: DB, cfg: Cfg) -> dict[str, bool]:
    previous = await smtp_config(db, cfg)
    config = body.model_dump()
    if not config["password"]:
        if config["host"] != previous.get("host"):
            raise HTTPException(422, "Re-enter the SMTP password when changing hosts")
        config["password"] = previous.get("password")
    if not config["password"]:
        raise HTTPException(422, "SMTP password is required (Gmail: use an app password)")
    if any(config[key] != previous.get(key) for key in config):
        if await load(db, ENABLED_KEY, False):
            raise HTTPException(409, "Disable 2FA before changing SMTP settings")
        config["verified"] = False
    else:
        config["verified"] = previous.get("verified", False)
    await save(db, CONFIG_KEY, encrypt(cfg.key_bytes, json.dumps(config)), True)
    await db.commit()
    return {"ok": True}


@router.post("/security/smtp/test")
async def test_smtp(db: DB, cfg: Cfg, admin: Admin) -> dict[str, Any]:
    if not admin.email:
        raise HTTPException(422, "Configure your admin email before testing SMTP")
    config = await smtp_config(db, cfg)
    try:
        link = await contact_link(db, cfg, admin, "email")
        await asyncio.to_thread(send_smtp, config, admin.email, "123456", link)
    except Exception:
        config["verified"] = False
        await save(db, CONFIG_KEY, encrypt(cfg.key_bytes, json.dumps(config)), True)
        await db.commit()
        return {"ok": False, "detail": "SMTP test failed. Check TLS, credentials and sender."}
    config["verified"] = True
    await save(db, CONFIG_KEY, encrypt(cfg.key_bytes, json.dumps(config)), True)
    await db.commit()
    return {
        "ok": True,
        "detail": "Test email accepted. Open its approval link to approve your email for 2FA.",
    }


class TwoFactorBody(BaseModel):
    enabled: bool


@router.put("/security/two-factor")
async def configure_two_factor(
    body: TwoFactorBody, db: DB, cfg: Cfg, admin: Admin, response: Response
) -> dict[str, bool]:
    if body.enabled:
        for user in (await db.execute(select(User))).scalars():
            await validate_contacts(db, user, True, cfg)
    if bool(await load(db, ENABLED_KEY, False)) != body.enabled:
        for user in (await db.execute(select(User))).scalars():
            user.auth_version += 1
    await save(db, ENABLED_KEY, body.enabled)
    await db.commit()
    _set_session_cookie(response, cfg, admin)
    return {"enabled": body.enabled}


class WhatsAppBody(BaseModel):
    api_url: str = "https://api.green-api.com"
    instance_id: str = Field(default="", max_length=30, pattern=r"^\d*$")
    token: str | None = Field(default=None, max_length=512, pattern=r"^[A-Za-z0-9_-]+$")

    @field_validator("api_url")
    @classmethod
    def valid_api_url(cls, value: str) -> str:
        parts = urlsplit(value.strip())
        host = parts.hostname or ""
        if (
            parts.scheme != "https"
            or parts.username
            or parts.password
            or parts.port
            or parts.query
            or parts.fragment
            or parts.path not in ("", "/")
            or not any(
                host == domain or host.endswith("." + domain)
                for domain in ("green-api.com", "greenapi.com")
            )
        ):
            raise ValueError("Use the HTTPS API URL from your GreenAPI console")
        return value.strip().rstrip("/")


@router.put("/security/whatsapp")
async def configure_whatsapp(body: WhatsAppBody, db: DB, cfg: Cfg) -> dict[str, bool]:
    if await load(db, ENABLED_KEY, False):
        raise HTTPException(409, "Disable 2FA before changing WhatsApp delivery settings")
    previous = await green_api_config(db, cfg)
    same_account = body.api_url == previous.get("api_url") and body.instance_id == previous.get(
        "instance_id"
    )
    token = body.token or (previous.get("token") if same_account else None)
    if not body.instance_id or not token:
        raise HTTPException(422, "GreenAPI instance ID and API token are required")
    config = {"api_url": body.api_url, "instance_id": body.instance_id, "token": token}
    config["verified"] = (
        bool(previous.get("verified"))
        if all(previous.get(k) == v for k, v in config.items())
        else False
    )
    await save(db, GREEN_API_KEY, encrypt(cfg.key_bytes, json.dumps(config)), True)
    await db.commit()
    return {"ok": True}


@router.post("/security/whatsapp/test")
async def test_whatsapp(db: DB, cfg: Cfg, admin: Admin) -> dict[str, Any]:
    if not admin.whatsapp_number:
        raise HTTPException(422, "Configure your personal WhatsApp number in Settings > Users")
    config = await green_api_config(db, cfg)
    try:
        link = await contact_link(db, cfg, admin, "whatsapp")
        await reserve_green(db, config, admin.whatsapp_number)
        await send_green_code(config, admin.whatsapp_number, "123456", link)
    except Exception as exc:
        if isinstance(exc, HTTPException) and exc.status_code == 429:
            raise
        config["verified"] = False
        await save(db, GREEN_API_KEY, encrypt(cfg.key_bytes, json.dumps(config)), True)
        await db.commit()
        return {
            "ok": False,
            "detail": "GreenAPI test failed. Check credentials and WhatsApp connection.",
        }
    config["verified"] = True
    await save(db, GREEN_API_KEY, encrypt(cfg.key_bytes, json.dumps(config)), True)
    await db.commit()
    return {
        "ok": True,
        "detail": "GreenAPI accepted the test message. "
        "Tap Approve WhatsApp to approve your number for 2FA.",
    }


class ContactApprovalBody(BaseModel):
    channel: Literal["email", "whatsapp"]


@router.post("/{user_id}/approve-contact")
async def request_contact_approval(
    user_id: int, body: ContactApprovalBody, db: DB, cfg: Cfg
) -> dict[str, bool]:
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "User not found")
    link = await contact_link(db, cfg, user, body.channel)
    try:
        if body.channel == "email":
            config = await smtp_config(db, cfg)
            if not config.get("verified"):
                raise HTTPException(422, "Test SMTP first in Settings > Notifications")
            assert user.email
            await asyncio.to_thread(send_smtp, config, user.email, "123456", link)
        else:
            config = await green_api_config(db, cfg)
            if not config.get("verified"):
                raise HTTPException(422, "Test GreenAPI first in Settings > Notifications")
            assert user.whatsapp_number
            await reserve_green(db, config, user.whatsapp_number)
            await send_green_code(config, user.whatsapp_number, "123456", link)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(503, "Approval message delivery failed. Try again later.") from None
    await db.commit()
    return {"ok": True}


@router.delete("/{user_id}", status_code=204)
async def delete_user(user_id: int, db: DB) -> Response:
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "User not found")
    if user.role == "admin":
        raise HTTPException(422, "Admin accounts cannot be deleted")
    await db.execute(delete(LoginChallenge).where(LoginChallenge.user_id == user_id))
    await db.execute(
        delete(Setting).where(
            Setting.key.startswith(CONTACT_PREFIX), Setting.value["user_id"].as_integer() == user_id
        )
    )
    await db.delete(user)
    await db.commit()
    return Response(status_code=204)
