"""Alert message text (spec 9.2) and the body-bound signed alert link.

The link's signature covers the alert id AND the whole message body above it, so a valid
signature validates only the exact text it was made for. A kid cannot paste a harmful message
under a copied link, nor reuse the signature of one alert on different text.
"""

import hashlib
import hmac
import re
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from app.alerts import ALERT_PREFIX, LEGACY_ALERT_PREFIX

MAX_QUOTE = 500

_CATEGORY_NAMES = {
    "harassment": "הטרדה",
    "harassment/threatening": "הטרדה מאיימת",
    "hate": "שנאה",
    "hate/threatening": "שנאה מאיימת",
    "illicit": "פעילות בלתי חוקית",
    "illicit/violent": "פעילות בלתי חוקית ואלימה",
    "self-harm": "פגיעה עצמית",
    "self-harm/instructions": "הנחיות לפגיעה עצמית",
    "self-harm/intent": "כוונה לפגיעה עצמית",
    "sexual": "תוכן מיני",
    "sexual/minors": "תוכן מיני עם קטינים",
    "violence": "אלימות",
    "violence/graphic": "אלימות גרפית",
}
_TYPE_NAMES = {
    "text": "טקסט",
    "image": "תמונה",
    "sticker": "מדבקה",
    "video": "סרטון",
    "voice": "הודעה קולית",
    "audio": "שמע",
    "document": "מסמך",
}

WITHHELD = "התוכן הוסתר (תוכן מיני). יש לבדוק את הצ׳אט ישירות."
# The link must be the LAST line: anything typed after it would not be covered by the signature.
_LINK_RE = re.compile(r"\n\n(?:פתיחה|Open): \S*/alerts/(\d+)\?s=([0-9a-f]{16})\Z")


def alert_signature(key: bytes, alert_id: int, body: str) -> str:
    digest = hashlib.sha256(body.encode()).hexdigest()
    return hmac.new(key, f"alert:{alert_id}:{digest}".encode(), hashlib.sha256).hexdigest()[:16]


def alert_link(base_url: str, key: bytes, alert_id: int, body: str) -> str:
    return f"{base_url}/alerts/{alert_id}?s={alert_signature(key, alert_id, body)}"


def with_signed_link(body: str, base_url: str, key: bytes, alert_id: int) -> str:
    return f"{body}\n\nפתיחה: {alert_link(base_url, key, alert_id, body)}"


def is_own_alert(text: str, key: bytes) -> bool:
    """True only for the exact text Iris produced: prefix, body, and a signature over that body."""
    if not text.startswith((ALERT_PREFIX, LEGACY_ALERT_PREFIX)):
        return False
    m = _LINK_RE.search(text)
    if m is None:
        return False
    body = text[: m.start()]
    return hmac.compare_digest(m.group(2), alert_signature(key, int(m.group(1)), body))


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
        body = f"[{_TYPE_NAMES.get(message_type, message_type)}]"
    return body if len(body) <= MAX_QUOTE else body[: MAX_QUOTE - 1] + "…"


@dataclass(frozen=True)
class MediaFact:
    media_id: int
    kind: str  # image | audio | video
    size_bytes: int


def human_size(n: int) -> str:
    if n < 1024:
        return f"{n} ב׳"
    if n < 1024 * 1024:
        return f"{n / 1024:.0f} ק״ב"
    return f"{n / (1024 * 1024):.1f} מ״ב"


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
    more_suppressed: int = 0
    media: "MediaFact | None" = None  # a kept copy of the media (never set for a redacted alert)


def format_alert(f: AlertFacts, timezone: str, base_url: str, key: bytes) -> str:
    when = f.sent_at
    if when.tzinfo is None:
        when = when.replace(tzinfo=ZoneInfo("UTC"))  # stored as naive UTC
    local = when.astimezone(ZoneInfo(timezone))
    top, *others = [_CATEGORY_NAMES.get(c, c) for c in f.categories]
    category = f"{top} ({f.max_score:.2f})" + (f", {', '.join(others)}" if others else "")
    sender = (f.sender_name or "?") + (" (הילד/ה שלך)" if f.from_me else "")
    lines = [
        ALERT_PREFIX,
        f"ילד/ה: {', '.join(f.kid_names)}",
        f"צ'אט: {f.chat_name or '?'} ({'קבוצה' if f.is_group else 'ישיר'})",
        f"מאת: {sender}",
        f"קטגוריה: {category}",
        f"שעה: {local.strftime('%d/%m %H:%M')}",
        "",
        WITHHELD if f.quote is None else f'"{f.quote}"',
    ]
    if f.media is not None and f.quote is not None:
        # In the body, before the signed link, so the signature covers it. It opens a portal page
        # that needs a login; the file itself is never reachable from this text alone.
        lines += [
            "",
            f"📎 מדיה נשמרה ({_TYPE_NAMES.get(f.media.kind, f.media.kind)}, "
            f"{human_size(f.media.size_bytes)}): "
            f"{base_url}/media/{f.media.media_id}",
        ]
    if f.more_suppressed:
        lines += ["", f"+{f.more_suppressed} התראות נוספות בצ'אט הזה מאז ההתראה האחרונה"]
    return with_signed_link("\n".join(lines), base_url, key, f.alert_id)


CHANGE_TEXT = {
    "edited": "נערכה על ידי השולח/ת",
    "revoked": "נמחקה אצל כולם על ידי השולח/ת",
}


def format_change_notice(kind: str, f: AlertFacts, timezone: str, base_url: str, key: bytes) -> str:
    """Follow-up after an alerted message changed. It never quotes content, so it is safe for
    redacted alerts too; the signed link opens the alert, where the portal shows the history."""
    when = f.sent_at
    if when.tzinfo is None:
        when = when.replace(tzinfo=ZoneInfo("UTC"))
    local = when.astimezone(ZoneInfo(timezone))
    sender = (f.sender_name or "?") + (" (הילד/ה שלך)" if f.from_me else "")
    lines = [
        ALERT_PREFIX,
        f"עדכון: ההודעה מהתראה מספר {f.alert_id} {CHANGE_TEXT[kind]}.",
        f"ילד/ה: {', '.join(f.kid_names)}",
        f"צ'אט: {f.chat_name or '?'} ({'קבוצה' if f.is_group else 'ישיר'})",
        f"מאת: {sender}",
        f"שעה: {local.strftime('%d/%m %H:%M')}",
    ]
    return with_signed_link("\n".join(lines), base_url, key, f.alert_id)
