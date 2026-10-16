from datetime import UTC, datetime

from app.alerts import ALERT_PREFIX
from app.alerts.format import (
    MAX_QUOTE,
    WITHHELD,
    AlertFacts,
    format_alert,
    is_own_alert,
    make_quote,
    with_signed_link,
)

KEY = b"k" * 32
BASE = "https://iris.example"


def facts(**kw: object) -> AlertFacts:
    base: dict[str, object] = dict(
        alert_id=7,
        kid_names=["Noa"],
        chat_name="Class 5B",
        is_group=True,
        sender_name="Dan",
        from_me=False,
        categories=["violence", "harassment"],
        max_score=0.944,
        sent_at=datetime(2026, 10, 6, 17, 5, tzinfo=UTC),
        quote="I will find you",
    )
    base.update(kw)
    return AlertFacts(**base)  # type: ignore[arg-type]


def text(tz: str = "Asia/Jerusalem", **kw: object) -> str:
    return format_alert(facts(**kw), tz, BASE, KEY)


def body_of(t: str) -> str:
    return t.rsplit("\n\nפתיחה: ", 1)[0]


def test_full_alert_layout_and_israel_time() -> None:
    t = text()
    assert body_of(t) == (
        "⚠️ התראת Iris\nילד/ה: Noa\nצ'אט: Class 5B (קבוצה)\nמאת: Dan\n"
        "קטגוריה: אלימות (0.94), הטרדה\nשעה: 06/10 20:05\n\n"
        '"I will find you"'
    )
    assert t.split("\n\nפתיחה: ")[1].startswith(f"{BASE}/alerts/7?s=")


def test_naive_stored_utc_time_is_treated_as_utc() -> None:
    assert "שעה: 15/01 12:00" in text(sent_at=datetime(2026, 1, 15, 10, 0))  # winter: UTC+2


def test_multi_kid_direct_chat_and_own_kid_marker() -> None:
    t = text("UTC", kid_names=["Noa", "Dan"], is_group=False, from_me=True, sender_name="Noa")
    assert "ילד/ה: Noa, Dan" in t and "(ישיר)" in t and "מאת: Noa (הילד/ה שלך)" in t


def test_redacted_alert_has_no_quote_and_withheld_notice() -> None:
    t = text("UTC", quote=None, categories=["sexual/minors"])
    assert WITHHELD in t and "I will find you" not in t and '"' not in t


def test_suppressed_count_line_comes_before_the_link() -> None:
    t = text("UTC", more_suppressed=3)
    assert "+3 התראות נוספות בצ'אט הזה מאז ההתראה האחרונה" in body_of(t)
    assert "התראות נוספות" not in text("UTC")


def test_quote_prefixes_and_truncation() -> None:
    assert make_quote("voice", None, "hello") == "🎤 hello"
    assert make_quote("image", "caption", None) == "🖼️ caption"
    assert make_quote("image", None, None) == "[תמונה]"
    assert make_quote("text", "plain", None) == "plain"
    assert make_quote("video", "cap", "spoken") == "🎤 spoken\ncap"
    long = make_quote("text", "x" * 900, None)
    assert len(long) == MAX_QUOTE and long.endswith("…")


# --- the signature is bound to the exact text ---------------------------------------------------


def test_real_alert_is_recognised_and_other_keys_are_not() -> None:
    real = text()
    assert is_own_alert(real, KEY)
    assert not is_own_alert(real, b"j" * 32)


def test_valid_link_pasted_under_harmful_text_is_not_recognised() -> None:
    """A kid who obtained one valid alert must not be able to hide other messages with it."""
    link_line = text().split("\n\nפתיחה: ")[1]
    forged = f"{ALERT_PREFIX}\nI will hurt you after school\n\nפתיחה: {link_line}"
    assert not is_own_alert(forged, KEY)


def test_any_edit_of_a_real_alert_breaks_the_signature() -> None:
    real = text()
    assert not is_own_alert(real.replace("Dan", "Eve"), KEY)
    assert not is_own_alert(real.replace('"I will find you"', '"something else"'), KEY)
    assert not is_own_alert(real.replace("/alerts/7?", "/alerts/8?"), KEY)


def test_text_after_the_link_or_before_the_prefix_is_rejected() -> None:
    real = text()
    assert not is_own_alert(real + "\nextra harmful words", KEY)
    assert not is_own_alert("hi\n" + real, KEY)
    assert not is_own_alert(real.replace(ALERT_PREFIX, "Hello", 1), KEY)
    assert not is_own_alert(f"{ALERT_PREFIX}\nOpen: {BASE}/alerts/7", KEY)  # unsigned


def test_test_message_signature_is_valid_only_for_its_own_text() -> None:
    """The test message goes to the parent's chat; its signature must not be a reusable pass."""
    test_msg = with_signed_link(f"{ALERT_PREFIX} (test)\nשליחת ההתראות פועלת.", BASE, KEY, 0)
    assert is_own_alert(test_msg, KEY)
    link_line = test_msg.split("\n\nפתיחה: ")[1]
    reused = f"{ALERT_PREFIX} (test)\nsomething harmful\n\nפתיחה: {link_line}"
    assert not is_own_alert(reused, KEY)


# --- kept media -------------------------------------------------------------------------------


def test_a_kept_file_adds_a_portal_link_before_the_signed_link() -> None:
    from app.alerts.format import MediaFact

    t = text(media=MediaFact(media_id=12, kind="image", size_bytes=1_300_000))
    assert f"📎 מדיה נשמרה (תמונה, 1.2 מ״ב): {BASE}/media/12" in t
    body = body_of(t)
    assert body.index("📎 מדיה נשמרה") > body.index('"I will find you"')  # after the quote
    assert t.endswith(f"?s={t.rsplit('?s=', 1)[1]}") and t.index("פתיחה:") > t.index("📎")
    assert is_own_alert(t, KEY)  # the loop guard still recognises Iris's own text


def test_the_media_line_is_covered_by_the_signature() -> None:
    from app.alerts.format import MediaFact

    t = text(media=MediaFact(media_id=12, kind="audio", size_bytes=900))
    forged = t.replace("/media/12", "/media/13")
    assert is_own_alert(t, KEY) and not is_own_alert(forged, KEY)
    assert "(שמע, 900 ב׳)" in t


def test_a_withheld_alert_never_links_media() -> None:
    from app.alerts.format import MediaFact

    t = text(quote=None, media=MediaFact(media_id=12, kind="image", size_bytes=10))
    assert "מדיה נשמרה" not in t and WITHHELD in t


def test_human_sizes() -> None:
    from app.alerts.format import human_size

    assert [human_size(n) for n in (5, 2048, 5 * 1024 * 1024)] == ["5 ב׳", "2 ק״ב", "5.0 מ״ב"]


def test_legacy_english_signed_alert_is_still_recognised() -> None:
    from app.alerts.format import alert_link

    body = "⚠️ Iris alert\nKid: Test"
    legacy = f"{body}\n\nOpen: {alert_link(BASE, KEY, 7, body)}"
    assert is_own_alert(legacy, KEY)
    assert not is_own_alert(legacy.replace("Kid: Test", "Kid: Changed"), KEY)


def test_hebrew_alert_has_translated_category_and_link() -> None:
    alert = text()
    assert alert.startswith("⚠️ התראת Iris")
    assert "קטגוריה: אלימות" in alert
    assert "\n\nפתיחה: " in alert
    assert is_own_alert(alert, KEY)
