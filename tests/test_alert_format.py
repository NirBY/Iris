from datetime import UTC, datetime

from app.alerts.format import (
    MAX_QUOTE,
    WITHHELD,
    AlertFacts,
    alert_link,
    format_alert,
    is_own_alert,
    make_quote,
)

KEY = b"k" * 32


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
        link="https://iris.example/alerts/7?s=abc",
    )
    base.update(kw)
    return AlertFacts(**base)  # type: ignore[arg-type]


def test_full_alert_layout_and_israel_time() -> None:
    assert format_alert(facts(), "Asia/Jerusalem") == (
        "⚠️ Iris alert\nKid: Noa\nChat: Class 5B (group)\nFrom: Dan\n"
        "Category: violence (0.94), harassment\nTime: 06/10 20:05\n\n"
        '"I will find you"\n\nOpen: https://iris.example/alerts/7?s=abc'
    )


def test_naive_stored_utc_time_is_treated_as_utc() -> None:
    naive = facts(sent_at=datetime(2026, 1, 15, 10, 0))
    assert "Time: 15/01 12:00" in format_alert(naive, "Asia/Jerusalem")  # winter: UTC+2


def test_multi_kid_direct_chat_and_own_kid_marker() -> None:
    t = format_alert(
        facts(kid_names=["Noa", "Dan"], is_group=False, from_me=True, sender_name="Noa"), "UTC"
    )
    assert "Kid: Noa, Dan" in t and "(direct)" in t and "From: Noa (your kid)" in t


def test_redacted_alert_has_no_quote_and_withheld_notice() -> None:
    t = format_alert(facts(quote=None, categories=["sexual/minors"]), "UTC")
    assert WITHHELD in t and "I will find you" not in t and '"' not in t


def test_suppressed_count_line() -> None:
    assert "+3 more alerts in this chat since last notification" in format_alert(
        facts(more_suppressed=3), "UTC"
    )
    assert "more alerts" not in format_alert(facts(), "UTC")


def test_quote_prefixes_and_truncation() -> None:
    assert make_quote("voice", None, "hello") == "🎤 hello"
    assert make_quote("image", "caption", None) == "🖼️ caption"
    assert make_quote("image", None, None) == "[image]"
    assert make_quote("text", "plain", None) == "plain"
    assert make_quote("video", "cap", "spoken") == "🎤 spoken\ncap"
    long = make_quote("text", "x" * 900, None)
    assert len(long) == MAX_QUOTE and long.endswith("…")


def test_signed_link_recognises_own_alerts_but_not_lookalikes() -> None:
    real = format_alert(facts(link=alert_link("https://iris.example", KEY, 7)), "UTC")
    assert is_own_alert(real, KEY)
    assert not is_own_alert(real, b"j" * 32)  # different key
    forged = real.replace(real.split("s=")[1][:12], "0" * 12)
    assert not is_own_alert(forged, KEY)  # copied format, bad signature
    assert not is_own_alert(
        "⚠️ Iris alert\nOpen: https://iris.example/alerts/7", KEY
    )  # no signature
    assert not is_own_alert(real.replace("⚠️ Iris alert", "Hello"), KEY)  # wrong prefix
