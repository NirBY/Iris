"""Alert transports share recipient checkpoints, while authentication keeps its own lane."""

import asyncio
import logging
import smtplib
import ssl
from email.message import EmailMessage
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import Instance, User
from app.openwa.client import OpenWAClient, OpenWAError
from app.security.crypto import decrypt
from app.security.two_factor import green_api_config, smtp_config
from app.settings_store import get_secret, get_setting


class _CredentialURLFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if "api.telegram.org/bot" in record.getMessage():
            record.msg, record.args = "Telegram HTTP request (credential URL redacted)", ()
        return True


logging.getLogger("httpx").addFilter(_CredentialURLFilter())


def send_email(config: dict[str, Any], address: str, text: str) -> None:
    message = EmailMessage()
    message["From"], message["To"] = config["sender"], address
    message["Subject"] = "Iris family alert"
    message.set_content(text)
    context = ssl.create_default_context()
    connection = (
        smtplib.SMTP_SSL(config["host"], config["port"], timeout=15, context=context)
        if config["tls"] == "ssl"
        else smtplib.SMTP(config["host"], config["port"], timeout=15)
    )
    with connection:
        if config["tls"] == "starttls":
            connection.starttls(context=context)
        connection.login(config["username"], config["password"])
        if connection.send_message(message):
            raise OpenWAError(400, "Email recipient rejected")


async def configured(db: AsyncSession, channel: str | None = None) -> bool:
    channel = channel or str(await get_setting(db, "alerts.channel"))
    cfg = get_settings()
    if not await get_setting(db, "alerts.recipient"):
        return False
    if channel == "openwa":
        sender_id = await get_setting(db, "alerts.sender_instance_id")
        sender = await db.get(Instance, sender_id) if sender_id else None
        return bool(sender and sender.openwa_api_key_enc)
    if channel == "smtp":
        return bool((await smtp_config(db, cfg)).get("verified"))
    if channel == "greenapi":
        return bool((await green_api_config(db, cfg)).get("verified"))
    return bool(await get_secret(db, "alerts.telegram_bot_token", cfg.key_bytes))


class ChannelClient:
    def __init__(
        self,
        channel: str,
        sender: Instance | None,
        config: dict[str, Any],
        contacts: dict[str, dict[str, str]],
        key: bytes,
    ):
        self.channel, self.config, self.contacts = channel, config, contacts
        self.openwa = None
        if channel == "openwa" and sender and sender.openwa_api_key_enc:
            self.openwa = OpenWAClient(
                sender.openwa_base_url, decrypt(key, sender.openwa_api_key_enc)
            )
        self.session_id = sender.openwa_instance_id if sender else ""
        self.sender_key = (
            f"openwa:{sender.id}"
            if channel == "openwa" and sender
            else f"alerts:greenapi:{config.get('instance_id', '')}"
            if channel == "greenapi"
            else f"alerts:{channel}"
        )

    async def aclose(self) -> None:
        if self.openwa:
            await self.openwa.aclose()

    async def send_text(self, _: str, target: str, text: str) -> None:
        contact = self.contacts.get(target, {})
        if self.channel in ("openwa", "greenapi") and target.startswith("email:"):
            raise OpenWAError(400, "This parent has no WhatsApp destination; use email alerts")
        if self.channel == "openwa":
            if not self.openwa:
                raise OpenWAError(401, "OpenWA sender unavailable")
            await self.openwa.send_text(self.session_id, target, text)
            return
        if self.channel == "smtp":
            address = contact.get("email") or (
                target.removeprefix("email:") if target.startswith("email:") else None
            )
            if not address:
                raise OpenWAError(400, "Parent email is missing")
            try:
                await asyncio.to_thread(send_email, self.config, address, text)
            except smtplib.SMTPAuthenticationError:
                raise OpenWAError(401, "SMTP authorization rejected") from None
            except smtplib.SMTPRecipientsRefused:
                raise OpenWAError(400, "Email recipient rejected") from None
            except (OSError, smtplib.SMTPException):
                raise OpenWAError(None, "Email delivery status uncertain") from None
            return
        if self.channel == "telegram":
            chat_id = contact.get("telegram_chat_id")
            if not chat_id:
                raise OpenWAError(400, "Parent Telegram chat ID is missing")
            url = f"https://api.telegram.org/bot{self.config['token']}/sendMessage"
            body = {"chat_id": chat_id, "text": text, "disable_web_page_preview": True}
        else:
            url = (
                f"{self.config['api_url']}/waInstance{self.config['instance_id']}"
                f"/sendMessage/{self.config['token']}"
            )
            body = {"chatId": target, "message": text}
        try:
            async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
                response = await client.post(url, json=body)
                if response.status_code >= 400:
                    raise OpenWAError(
                        response.status_code, "Notification provider rejected request"
                    )
                result = response.json()
                if self.channel == "telegram" and result.get("ok") is not True:
                    raise OpenWAError(
                        int(result.get("error_code", 400)), "Telegram rejected request"
                    )
                if self.channel == "greenapi" and not result.get("idMessage"):
                    raise OpenWAError(None, "GreenAPI delivery status uncertain")
        except (httpx.HTTPError, ValueError):
            raise OpenWAError(None, "Notification delivery status uncertain") from None


async def build_client(
    db: AsyncSession, sender: Instance | None, key: bytes, channel: str | None = None
) -> ChannelClient:
    channel = channel or str(await get_setting(db, "alerts.channel"))
    cfg = get_settings()
    contacts = dict(await get_setting(db, "alerts.recipient_contacts"))
    # Registered users supply their approved email automatically; explicit parent
    # destinations take precedence and remain independent from sign-in credentials.
    for user in await db.scalars(select(User)):
        if user.email and user.email_verified:
            email_target = "email:" + user.email.lower()
            contacts[email_target] = {"email": user.email, **contacts.get(email_target, {})}
        if user.whatsapp_number and user.email and user.email_verified:
            parent = user.whatsapp_number.lstrip("+") + "@c.us"
            contacts[parent] = {"email": user.email, **contacts.get(parent, {})}
    if channel == "smtp":
        config = await smtp_config(db, cfg)
    elif channel == "greenapi":
        config = await green_api_config(db, cfg)
    elif channel == "telegram":
        config = {"token": await get_secret(db, "alerts.telegram_bot_token", key)}
    else:
        config = {}
    return ChannelClient(channel, sender, config, contacts, key)
