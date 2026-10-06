import json
from typing import Any

from sqlalchemy import update

from app.api.messages import MARK_END, MARK_START
from app.db.models import Message
from tests.test_webhooks import fx, make_instance, post


async def seed(c: Any) -> dict[str, Any]:
    i1, t1 = await make_instance(c, "Noa")
    i2, t2 = await make_instance(c, "Dan")
    await post(c, t1, fx("text_sent_he"))
    await post(c, t1, fx("text_received_mixed"))
    await post(c, t1, fx("group_text_received"))
    await post(c, t2, fx("group_text_received"))  # same group message, second kid
    await post(c, t1, fx("image_caption_sent"))
    return {"i1": i1, "i2": i2}


async def test_list_and_pagination(app_client: Any) -> None:
    await seed(app_client)
    r = (await app_client.get("/api/messages", params={"page_size": 2})).json()
    assert r["total"] == 4 and len(r["items"]) == 2 and r["page_size"] == 2
    r2 = (await app_client.get("/api/messages", params={"page_size": 2, "page": 2})).json()
    assert {i["id"] for i in r["items"]}.isdisjoint({i["id"] for i in r2["items"]})
    assert (await app_client.get("/api/messages", params={"page_size": 101})).status_code == 422


async def test_hebrew_search_with_snippet_markers(app_client: Any) -> None:
    await seed(app_client)
    r = (await app_client.get("/api/messages", params={"q": "הודעת"})).json()
    assert r["total"] >= 1
    assert all(MARK_START in i["snippet"] and MARK_END in i["snippet"] for i in r["items"])


async def test_search_prefix_and_special_chars_are_safe(app_client: Any) -> None:
    await seed(app_client)
    assert (await app_client.get("/api/messages", params={"q": "mix"})).json()["total"] == 1
    for evil in ['"', "a OR b", "*", "NEAR(", "x' --", "(((", "שלום OR"]:
        assert (await app_client.get("/api/messages", params={"q": evil})).status_code == 200


async def test_filters(app_client: Any) -> None:
    ids = await seed(app_client)
    g = app_client.get
    assert (await g("/api/messages", params={"instance_id": ids["i2"]})).json()["total"] == 1
    assert (await g("/api/messages", params={"instance_id": ids["i1"]})).json()["total"] == 4
    assert (await g("/api/messages", params={"type": "image"})).json()["total"] == 1
    assert (await g("/api/messages", params={"sender": "Group"})).json()["total"] == 1
    assert (await g("/api/messages", params={"sender": "%"})).json()["total"] == 0  # escaped LIKE
    assert (await g("/api/messages", params={"verdict": "none"})).json()["total"] == 4
    assert (await g("/api/messages", params={"from": "2030-01-01T00:00:00Z"})).json()["total"] == 0
    assert (await g("/api/messages", params={"to": "2020-01-01T00:00:00Z"})).json()["total"] == 0


async def test_multi_kid_shown_on_group_message(app_client: Any) -> None:
    await seed(app_client)
    items = (await app_client.get("/api/messages", params={"sender": "Group"})).json()["items"]
    assert [k["kid_name"] for k in items[0]["kids"]] == ["Noa", "Dan"]


async def test_redacted_content_is_hidden_and_unsearchable(app_client: Any) -> None:
    await seed(app_client)
    async with app_client.app.state.session_factory() as s:
        await s.execute(
            update(Message).where(Message.type == "text").values(text="[redacted]", redacted=True)
        )
        await s.commit()
    r = (await app_client.get("/api/messages", params={"type": "text"})).json()
    assert r["items"] and all(i["redacted"] and i["text"] is None for i in r["items"])
    assert (await app_client.get("/api/messages", params={"q": "הודעת"})).json()["total"] == 0
    assert "הודעת בדיקה" not in json.dumps(
        (await app_client.get("/api/messages")).json(), ensure_ascii=False
    ).replace("תמונה", "")


async def test_detail_and_context(app_client: Any) -> None:
    await seed(app_client)
    items = (await app_client.get("/api/messages")).json()["items"]
    mid = items[0]["id"]
    d = (await app_client.get(f"/api/messages/{mid}")).json()
    assert d["id"] == mid and d["classifications"] == []
    ctx = (await app_client.get(f"/api/messages/{mid}/context", params={"radius": 1})).json()
    assert mid in [c["id"] for c in ctx] and len(ctx) <= 3
    assert (await app_client.get("/api/messages/99999")).status_code == 404


async def test_messages_require_auth(app_client: Any) -> None:
    app_client.cookies.clear()
    assert (await app_client.get("/api/messages")).status_code == 401
