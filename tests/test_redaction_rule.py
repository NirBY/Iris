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
async def test_an_alerted_uncertain_item_quotes_its_text(app_client: Any) -> None:
    deps, token, _ = await setup(app_client)
    await app_client.put("/api/settings", json={"settings": {"alerts.alert_on_review": True}})
    respx.post(MOD_URL).mock(return_value=mod_response(**{M: UNCERTAIN}))
    await post(app_client, token, msg_body("text_received_mixed", "UNC3", "worth a look"))
    await run_all(deps)
    await deps.providers.aclose()
    async with app_client.app.state.session_factory() as s:
        (alert,) = (await s.execute(select(Alert))).scalars().all()
    assert alert.quote == "worth a look" and not (await _message(app_client)).redacted
