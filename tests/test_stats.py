from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, update

from app.alerts.service import create_alert
from app.db.models import Instance, Job, Message
from tests.test_alerts import msg_body
from tests.test_webhooks import fx, make_instance, post


async def test_stats_empty_database(app_client: Any) -> None:
    s = (await app_client.get("/api/stats")).json()
    assert s["messages_today"] == 0 and s["queue_depth"] == 0 and s["failed_jobs"] == 0
    assert s["delivery_configured"] is False and s["instances"] == 0 and s["review_queue"] == 0


async def test_stats_counts(app_client: Any) -> None:
    _, token = await make_instance(app_client, "Noa")
    await make_instance(app_client, "Silent")  # never receives a webhook
    now = datetime.now(UTC)
    for i, age_days in enumerate((0, 3, 20)):
        body = msg_body("text_received_mixed", f"ST0{i}", f"m{i}")
        import json

        b = json.loads(body)
        b["data"]["timestamp"] = int((now - timedelta(days=age_days, minutes=1)).timestamp())
        await post(app_client, token, json.dumps(b).encode())
    async with app_client.app.state.session_factory() as s:
        msgs = (await s.execute(select(Message).order_by(Message.id))).scalars().all()
        msgs[1].verdict = "review"
        await create_alert(s, msgs[0], {"violence": 0.9})
        await s.execute(update(Job).where(Job.id == 2).values(status="failed"))
        await s.commit()
    st = (await app_client.get("/api/stats")).json()
    assert st["messages_7d"] == 2 and st["messages_today"] >= 1
    assert st["alerts_by_status"] == {"new": 1} and st["alerts_by_delivery"] == {"failed": 1}
    assert st["review_queue"] == 1 and st["failed_jobs"] == 1
    assert st["queue_depth"] == 2  # three ingest jobs, one of them marked failed
    assert st["instances"] == 2 and st["silent_instances"] == 1


async def test_chats_list_with_kids_and_counts(app_client: Any) -> None:
    _, t1 = await make_instance(app_client, "Noa")
    _, t2 = await make_instance(app_client, "Dan")
    await post(app_client, t1, fx("group_text_received"))
    await post(app_client, t2, fx("group_text_received"))  # same group: two kids
    await post(app_client, t1, fx("text_received_mixed"))
    async with app_client.app.state.session_factory() as s:
        m = (await s.execute(select(Message).where(Message.chat_id == 1))).scalars().first()
        assert m
        await create_alert(s, m, {"hate": 0.8})
    chats = (await app_client.get("/api/chats")).json()
    group = next(c for c in chats if c["is_group"])
    assert [k["kid_name"] for k in group["kids"]] == ["Noa", "Dan"]
    assert group["message_count"] == 1 and group["alert_count"] == 1
    direct = next(c for c in chats if not c["is_group"])
    assert (
        direct["message_count"] == 1
        and direct["alert_count"] == 0
        and direct["name"] == "Kid Tester"
    )


async def test_stats_and_chats_require_auth(app_client: Any) -> None:
    app_client.cookies.clear()
    assert (await app_client.get("/api/stats")).status_code == 401
    assert (await app_client.get("/api/chats")).status_code == 401
    assert Instance and Job
