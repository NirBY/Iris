"""The withholding rule: uncertain text is kept for review; clear or confirmed cases are not."""

from typing import Any

import pytest
import respx
from sqlalchemy import select

from app.alerts.service import needs_redaction, redact_for_alert
from app.classify.moderation import URL as MOD_URL
from app.classify.thresholds import DEFAULT_THRESHOLDS
from app.db.models import Alert, Message, MessageRevision
from tests.test_alerts import msg_body, run_all, setup
from tests.test_webhooks import post
from tests.test_worker import mod_response

M = "sexual/minors"
UNCERTAIN = 0.10  # above low (0.05), below high (0.30)
CLEAR = 0.60


@pytest.mark.parametrize(
    ("mtype", "high", "low", "withheld"),
    [
        ("text", [M], [M], True),  # clear: withheld
        ("text", [], [M], False),  # uncertain text: kept for review
        ("voice", [], [M], False),  # a transcript is words too
        ("audio", [], [M], False),
        ("image", [], [M], True),  # anything with a picture: withheld at any band
        ("sticker", [], [M], True),
        ("video", [], [M], True),
        ("text", [], [], False),
        ("image", ["sexual"], ["sexual"], True),  # sexual imagery at the high threshold
        ("image", [], ["sexual"], False),  # only uncertain sexual imagery: not yet
        ("text", ["sexual"], ["sexual"], False),  # adult text alone is not withheld
    ],
)
def test_classification_time_decision(
    mtype: str, high: list[str], low: list[str], withheld: bool
) -> None:
    assert needs_redaction(mtype, high, low) is withheld


@pytest.mark.parametrize(
    ("mtype", "scores", "confirmed", "withheld"),
    [
        ("text", {M: UNCERTAIN}, False, False),
        ("text", {M: UNCERTAIN}, True, True),  # the owner confirmed it: withheld now
        ("text", {M: CLEAR}, False, True),
        ("voice", {M: UNCERTAIN}, False, False),
        ("image", {M: UNCERTAIN}, False, True),
        ("text", {"violence": 0.9}, False, False),
        ("text", {"violence": 0.9}, True, False),  # confirming something else withholds nothing
        ("image", {"sexual": 0.4}, False, True),
        ("text", {"sexual": 0.9}, False, False),
    ],
)
def test_alert_time_decision(
    mtype: str, scores: dict[str, float], confirmed: bool, withheld: bool
) -> None:
    assert redact_for_alert(mtype, scores, DEFAULT_THRESHOLDS, confirmed) is withheld


async def _message(c: Any) -> Message:
    async with c.app.state.session_factory() as s:
        return (await s.execute(select(Message))).scalar_one()


async def _classify(c: Any, score: float, text: str = "an uncertain sentence") -> Message:
    deps, token, _ = await setup(c)
    respx.post(MOD_URL).mock(return_value=mod_response(**{M: score}))
    await post(c, token, msg_body("text_received_mixed", "UNC1", text))
    await run_all(deps)
    await deps.providers.aclose()
    return await _message(c)


@respx.mock
async def test_uncertain_text_is_kept_and_waits_for_review(app_client: Any) -> None:
    m = await _classify(app_client, UNCERTAIN)
    assert m.verdict == "review" and not m.redacted and m.text == "an uncertain sentence"
    q = (await app_client.get("/api/review")).json()["items"]
    assert [i["message"]["text"] for i in q] == ["an uncertain sentence"]
    found = (await app_client.get("/api/messages", params={"q": "uncertain"})).json()
    assert found["total"] == 1


@respx.mock
async def test_clearly_harmful_text_is_still_withheld(app_client: Any) -> None:
    m = await _classify(app_client, CLEAR, "something clearly bad")
    assert m.redacted and m.text == "[redacted]" and m.verdict == "harmful"


@respx.mock
async def test_marking_an_uncertain_item_safe_keeps_it_readable(app_client: Any) -> None:
    m = await _classify(app_client, UNCERTAIN)
    r = await app_client.post(f"/api/review/{m.id}", json={"resolution": "safe"})
    assert r.status_code == 200
    after = await _message(app_client)
    assert after.verdict == "safe" and not after.redacted and after.text == "an uncertain sentence"


@respx.mock
async def test_marking_it_harmful_withholds_it_at_that_moment(app_client: Any) -> None:
    m = await _classify(app_client, UNCERTAIN, "an edited sentence")
    async with app_client.app.state.session_factory() as s:  # it was edited once, so it has history
        s.add(MessageRevision(message_id=m.id, text="the original wording"))
        await s.commit()
    r = await app_client.post(f"/api/review/{m.id}", json={"resolution": "harmful"})
    assert r.status_code == 200
    after = await _message(app_client)
    assert after.redacted and after.text == "[redacted]" and after.transcript == "[redacted]"
    async with app_client.app.state.session_factory() as s:
        assert (await s.execute(select(MessageRevision))).scalars().all() == []
        (alert,) = (await s.execute(select(Alert))).scalars().all()
        assert alert.quote is None  # the alert never quotes withheld text
    assert (await app_client.get("/api/messages", params={"q": "sentence"})).json()["total"] == 0


@respx.mock
async def test_an_uncertain_image_is_withheld_at_once(app_client: Any) -> None:
    from tests.test_media_pipeline import serve

    deps, token, _ = await setup(app_client)
    serve("image.png", "image/png")
    respx.post(MOD_URL).mock(return_value=mod_response(**{M: UNCERTAIN}))
    await post(app_client, token, msg_body("image_caption_sent", "UNC2", "a caption"))
    await run_all(deps)
    await deps.providers.aclose()
    m = await _message(app_client)
    assert m.redacted and m.text == "[redacted]"


@respx.mock
async def test_an_alerted_uncertain_item_is_kept_but_not_quoted(app_client: Any) -> None:
    deps, token, _ = await setup(app_client)
    await app_client.put("/api/settings", json={"settings": {"alerts.alert_on_review": True}})
    respx.post(MOD_URL).mock(return_value=mod_response(**{M: UNCERTAIN}))
    await post(app_client, token, msg_body("text_received_mixed", "UNC3", "worth a look"))
    await run_all(deps)
    await deps.providers.aclose()
    async with app_client.app.state.session_factory() as s:
        (alert,) = (await s.execute(select(Alert))).scalars().all()
    # Kept for the owner to read in the portal, but never copied into an alert.
    assert alert.quote is None and not (await _message(app_client)).redacted
    assert (await _message(app_client)).text == "worth a look"


# --- review findings ---------------------------------------------------------------------------


@respx.mock
async def test_confirming_withholds_even_when_an_alert_already_exists(app_client: Any) -> None:
    deps, token, _ = await setup(app_client)
    await app_client.put("/api/settings", json={"settings": {"alerts.alert_on_review": True}})
    respx.post(MOD_URL).mock(return_value=mod_response(**{M: UNCERTAIN}))
    await post(app_client, token, msg_body("text_received_mixed", "UNC4", "text to be confirmed"))
    await run_all(deps)
    async with app_client.app.state.session_factory() as s:
        (alert,) = (await s.execute(select(Alert))).scalars().all()
        assert alert.quote is None  # an uncertain item is never copied into an alert
    m = await _message(app_client)
    assert not m.redacted and m.text == "text to be confirmed"
    r = await app_client.post(f"/api/review/{m.id}", json={"resolution": "harmful"})
    assert r.status_code == 200
    after = await _message(app_client)
    assert after.redacted and after.text == "[redacted]"
    assert (await app_client.get("/api/messages", params={"q": "confirmed"})).json()["total"] == 0
    await deps.providers.aclose()


@respx.mock
async def test_uncertain_text_is_never_sent_over_whatsapp(app_client: Any) -> None:
    import json

    import httpx

    from tests.test_alerts import SEND_URL

    deps, token, _ = await setup(app_client)
    await app_client.put("/api/settings", json={"settings": {"alerts.alert_on_review": True}})
    send = respx.post(SEND_URL).mock(return_value=httpx.Response(201, json={}))
    respx.post(MOD_URL).mock(return_value=mod_response(**{M: UNCERTAIN, "harassment": 0.9}))
    await post(app_client, token, msg_body("text_received_mixed", "UNC5", "secretly uncertain"))
    await run_all(deps)
    sent = json.loads(send.calls.last.request.content)["text"]
    assert "secretly uncertain" not in sent
    async with app_client.app.state.session_factory() as s:
        (alert,) = (await s.execute(select(Alert))).scalars().all()
    assert alert.quote is None
    detail = (await app_client.get(f"/api/alerts/{alert.id}")).json()
    assert detail["quote"] is None and detail["redacted"] is False
    await deps.providers.aclose()


@respx.mock
async def test_a_flag_cleared_by_a_later_stage_still_counts_when_confirming(
    app_client: Any,
) -> None:
    deps, token, _ = await setup(app_client)
    respx.post(MOD_URL).mock(
        side_effect=[
            mod_response(),  # an earlier message in the chat
            mod_response(**{M: UNCERTAIN}),  # first look: uncertain
            mod_response(harassment=0.4),  # the second look no longer flags minors
        ]
    )
    await post(app_client, token, msg_body("text_received_mixed", "OLD1", "earlier line", -60))
    await post(app_client, token, msg_body("text_received_mixed", "STG1", "stage text"))
    await run_all(deps)
    async with app_client.app.state.session_factory() as s:
        m = (await s.execute(select(Message).where(Message.text == "stage text"))).scalar_one()
    assert m.verdict == "review" and not m.redacted
    r = await app_client.post(f"/api/review/{m.id}", json={"resolution": "harmful"})
    assert r.status_code == 200
    async with app_client.app.state.session_factory() as s:
        assert (await s.get(Message, m.id)).redacted is True  # type: ignore[union-attr]
    await deps.providers.aclose()


def test_custom_thresholds_move_the_line() -> None:
    strict = {**DEFAULT_THRESHOLDS, M: (0.02, 0.08)}
    loose = {**DEFAULT_THRESHOLDS, M: (0.05, 0.90)}
    assert redact_for_alert("text", {M: 0.10}, strict, False) is True
    assert redact_for_alert("text", {M: 0.10}, loose, False) is False
    assert redact_for_alert("text", {M: 0.30}, DEFAULT_THRESHOLDS, False) is True  # exactly high
    assert redact_for_alert("text", {M: 0.2999}, DEFAULT_THRESHOLDS, False) is False


@respx.mock
async def test_an_uncertain_voice_transcript_is_kept_for_review(app_client: Any) -> None:
    import httpx

    from app.transcription import openai as openai_t
    from tests.test_media_pipeline import serve
    from tests.test_webhooks import fx

    deps, token, _ = await setup(app_client)
    serve("voice.ogg", "audio/ogg")
    respx.post(openai_t.URL).mock(return_value=httpx.Response(200, json={"text": "spoken words"}))
    respx.post(MOD_URL).mock(return_value=mod_response(**{M: UNCERTAIN}))
    await post(app_client, token, fx("voice_sent"))
    await run_all(deps)
    m = await _message(app_client)
    assert m.type == "voice" and m.verdict == "review" and not m.redacted
    assert m.transcript == "spoken words"
    await deps.providers.aclose()
