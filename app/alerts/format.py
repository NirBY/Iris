"""Alert message text (spec 9.2) and the signed alert link."""

import hashlib
import hmac
import re
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from app.alerts import ALERT_PREFIX

MAX_QUOTE = 500
WITHHELD = "Content withheld (sexual content). Review the chat directly."
_LINK_RE = re.compile(r"/alerts/(\d+)\?s=([0-9a-f]{12})")


def alert_signature(key: bytes, alert_id: int) -> str:
    return hmac.new(key, f"alert:{alert_id}".encode(), hashlib.sha256).hexdigest()[:12]


def alert_link(base_url: str, key: bytes, alert_id: int) -> str:
    return f"{base_url}/alerts/{alert_id}?s={alert_signature(key, alert_id)}"


def is_own_alert(text: str, key: bytes) -> bool:
    """True only for text carrying a valid signed link: an alert typed by someone else
    (even one copying the format) fails this, so it cannot be used to dodge monitoring."""
    if not text.startswith(ALERT_PREFIX):
        return False
    return any(
        hmac.compare_digest(sig, alert_signature(key, int(aid)))
        for aid, sig in _LINK_RE.findall(text)
    )


def make_quote(message_type: str, text: str | None, transcript: str | None) -> str:
    """The quoted content: transcripts get 🎤, image captions 🖼️, bare images `[image]`."""
    if transcript and not text:
        body = f"🎤 {transcript}"
    elif transcript and text:
        body = f"🎤 {transcript}\n{text}"
    elif text and message_type in ("image", "sticker", "video"):
        body = f"🖼️ {text}"
    elif text:
        body = text
    else:
        body = f"[{message_type}]"
    return body if len(body) <= MAX_QUOTE else body[: MAX_QUOTE - 1] + "…"


@dataclass(frozen=True)
class AlertFacts:
    alert_id: int
    kid_names: list[str]
    chat_name: str | None
    is_group: bool
    sender_name: str | None
    from_me: bool
    categories: list[str]  # most severe first
    max_score: float
    sent_at: datetime
    quote: str | None  # None when redacted
    link: str
    more_suppressed: int = 0


def format_alert(f: AlertFacts, timezone: str) -> str:
    when = f.sent_at
    if when.tzinfo is None:
        when = when.replace(tzinfo=ZoneInfo("UTC"))  # stored as naive UTC
    local = when.astimezone(ZoneInfo(timezone))
    top, others = f.categories[0], f.categories[1:]
    category = f"{top} ({f.max_score:.2f})" + (f", {', '.join(others)}" if others else "")
    sender = (f.sender_name or "?") + (" (your kid)" if f.from_me else "")
    lines = [
        ALERT_PREFIX,
        f"Kid: {', '.join(f.kid_names)}",
        f"Chat: {f.chat_name or '?'} ({'group' if f.is_group else 'direct'})",
        f"From: {sender}",
        f"Category: {category}",
        f"Time: {local.strftime('%d/%m %H:%M')}",
        "",
        WITHHELD if f.quote is None else f'"{f.quote}"',
        "",
    ]
    if f.more_suppressed:
        lines += [f"+{f.more_suppressed} more alerts in this chat since last notification", ""]
    lines.append(f"Open: {f.link}")
    return "\n".join(lines)
