import json
from datetime import datetime
from typing import Any

import respx
from sqlalchemy import select, update

from app.alerts.service import create_alert
from app.classify.moderation import URL as MOD_URL
from app.db.models import Alert, Classification, Message
from tests.test_alerts import msg_body, run_all, setup
from tests.test_webhooks import fx, make_instance, post
from tests.test_worker import mod_response


async def seeded(c: Any) -> list[int]:
    """Three messages (two kids, two chats) with alerts of different categories."""
    _, t1 = await make_instance(c, "Noa")
    i2, t2 = await make_instance(c, "Dan")
    await post(c, t1, msg_body("text_received_mixed", "AAA1", "one"))
    await post(c, t2, msg_body("text_received_mixed", "AAA2", "two"))
    await post(c, t1, fx("group_text_received"))
    async with c.app.state.session_factory() as s:
        msgs = (await s.execute(select(Message).order_by(Message.id))).scalars().all()
        for m, cats in zip(
            msgs,
            ({"violence": 0.9}, {"harassment": 0.8, "hate": 0.4}, {"self-harm": 0.7}),
            strict=True,
        ):
            await create_alert(s, m, cats)
    return [m.id for m in msgs] + [i2]


async def test_list_filters_and_pagination(app_client: Any) -> None:
    *_, i2 = await seeded(app_client)
    g = app_client.get
    assert (await g("/api/alerts")).json()["total"] == 3
    assert (await g("/api/alerts", params={"category": "violence"})).json()["total"] == 1
    assert (await g("/api/alerts", params={"category": "hate"})).json()[
        "total"
    ] == 1  # secondary category
    assert (await g("/api/alerts", params={"category": "nope"})).json()["total"] == 0
    assert (await g("/api/alerts", params={"category": "x' OR '1'='1"})).json()["total"] == 0
    assert (await g("/api/alerts", params={"instance_id": i2})).json()["total"] == 1
    assert (await g("/api/alerts", params={"delivery_status": "failed"})).json()["total"] == 3
    assert (await g("/api/alerts", params={"from": "2030-01-01T00:00:00Z"})).json()["total"] == 0
    page = (await g("/api/alerts", params={"page_size": 2})).json()
    assert len(page["items"]) == 2 and page["total"] == 3
    assert (await g("/api/alerts", params={"page_size": 101})).status_code == 422
    one_chat = (await g("/api/alerts")).json()["items"][0]["chat_id"]
    assert (await g("/api/alerts", params={"chat_id": one_chat})).json()["total"] >= 1


async def test_status_change_and_detail(app_client: Any) -> None:
    await seeded(app_client)
    r = await app_client.patch("/api/alerts/1", json={"status": "acknowledged"})
    assert r.json()["status"] == "acknowledged"
    assert (await app_client.get("/api/alerts", params={"status": "acknowledged"})).json()[
        "total"
    ] == 1
    assert (await app_client.patch("/api/alerts/1", json={"status": "bogus"})).status_code == 422
    d = (await app_client.get("/api/alerts/1")).json()
    assert (
        d["categories"] == ["violence"] and d["message_type"] == "text" and d["redacted"] is False
    )
    assert (await app_client.get("/api/alerts/999")).status_code == 404
    assert (
        await app_client.post("/api/alerts/1/resend")
    ).status_code == 422  # delivery not configured


async def test_alerts_and_review_require_auth(app_client: Any) -> None:
    app_client.cookies.clear()
    for path in ("/api/alerts", "/api/alerts/1", "/api/review"):
        assert (await app_client.get(path)).status_code == 401
    assert (await app_client.post("/api/review/1", json={"resolution": "safe"})).status_code == 401


@respx.mock
async def test_review_queue_resolve_safe_and_harmful(app_client: Any) -> None:
    deps, token, _ = await setup(app_client, recipient=None)
    respx.post(MOD_URL).mock(
        return_value=mod_response(violence=0.4)
    )  # inconclusive twice -> review
    await post(app_client, token, msg_body("text_received_mixed", "RV01", "borderline one"))
    await post(app_client, token, msg_body("text_received_mixed", "RV02", "borderline two", 5))
    await run_all(deps)
    q = (await app_client.get("/api/review")).json()
    assert q["total"] == 2
    item = q["items"][0]
    assert (
        item["message"]["verdict"] == "review"
        and item["classifications"][-1]["band"] == "inconclusive"
    )
    first, second = (i["message"]["id"] for i in q["items"])

    safe = await app_client.post(f"/api/review/{first}", json={"resolution": "safe"})
    assert safe.json() == {"ok": True, "verdict": "safe", "alert_id": None}
    harmful = await app_client.post(f"/api/review/{second}", json={"resolution": "harmful"})
    body = harmful.json()
    assert body["verdict"] == "harmful" and body["alert_id"]
    a = (await app_client.get(f"/api/alerts/{body['alert_id']}")).json()
    assert a["categories"] == ["violence"]  # the categories that made it inconclusive
    assert (await app_client.get("/api/review")).json()["total"] == 0
    # already resolved: not awaiting review any more
    assert (
        await app_client.post(f"/api/review/{first}", json={"resolution": "harmful"})
    ).status_code == 409
    assert (
        await app_client.post("/api/review/999", json={"resolution": "safe"})
    ).status_code == 404
    assert (
        await app_client.post(f"/api/review/{second}", json={"resolution": "nope"})
    ).status_code == 422
    await deps.providers.aclose()


@respx.mock
async def test_uncertain_minors_text_is_kept_for_review(
    app_client: Any,
) -> None:
    """Between low (0.05) and high (0.30): inconclusive -> review. The owner must be able to read it
    to decide, so the text is kept (the portal still hides it until the eye is pressed)."""
    deps, token, _ = await setup(app_client, recipient=None)
    text = "borderline words to judge"
    respx.post(MOD_URL).mock(return_value=mod_response(**{"sexual/minors": 0.12}))
    await post(app_client, token, msg_body("text_received_mixed", "LOW1", text))
    await post(app_client, token, msg_body("text_received_mixed", "LOW2", "x", 3))
    await run_all(deps)
    async with app_client.app.state.session_factory() as s:
        m = (await s.execute(select(Message).order_by(Message.id))).scalars().first()
        assert m and m.verdict == "review" and not m.redacted and m.text == text
    assert text in (await app_client.get("/api/review")).text
    assert (await app_client.get("/api/messages", params={"q": "borderline"})).json()["total"] == 1
    await deps.providers.aclose()


@respx.mock
async def test_minors_at_or_above_the_high_threshold_is_withheld(app_client: Any) -> None:
    deps, token, _ = await setup(app_client, recipient=None)
    secret = "CLEARLYWITHHELDTEXT"
    respx.post(MOD_URL).mock(return_value=mod_response(**{"sexual/minors": 0.30}))
    await post(app_client, token, msg_body("text_received_mixed", "HI01", secret))
    await run_all(deps)
    async with app_client.app.state.session_factory() as s:
        m = (await s.execute(select(Message))).scalar_one()
        assert m.redacted and m.text == "[redacted]"
    assert secret not in (await app_client.get("/api/messages")).text
    await deps.providers.aclose()


@respx.mock
async def test_below_low_threshold_is_not_redacted(app_client: Any) -> None:
    deps, token, _ = await setup(app_client, recipient=None)
    respx.post(MOD_URL).mock(return_value=mod_response(**{"sexual/minors": 0.01}))
    await post(app_client, token, msg_body("text_received_mixed", "OK01", "fine"))
    await run_all(deps)
    async with app_client.app.state.session_factory() as s:
        m = (await s.execute(select(Message))).scalar_one()
        assert m.verdict == "safe" and not m.redacted and m.text == "fine"
    await deps.providers.aclose()


async def test_existing_alert_and_classification_survive_redaction_metadata_only(
    app_client: Any,
) -> None:
    await seeded(app_client)
    async with app_client.app.state.session_factory() as s:
        alert = (await s.execute(select(Alert).where(Alert.id == 1))).scalar_one()
        await s.execute(update(Message).where(Message.id == alert.message_id).values(redacted=True))
        s.add(
            Classification(
                message_id=alert.message_id,
                stage="moderation",
                input_kind="text",
                model="m",
                scores={"violence": 0.9},
                flagged_categories=["violence"],
                band="harmful",
            )
        )
        await s.commit()
    d = (await app_client.get("/api/alerts/1")).json()
    assert d["quote"] is None and d["redacted"] is True and d["classifications"]
    listed = (await app_client.get("/api/alerts")).json()["items"]
    assert all(i["quote"] is None for i in listed if i["id"] == 1)
    assert json.dumps(d) and isinstance(datetime.fromisoformat(d["created_at"]), datetime)
