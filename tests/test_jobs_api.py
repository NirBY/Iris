from typing import Any

from sqlalchemy import select, update

from app.db.models import Job, Message
from tests.test_webhooks import fx, make_instance, post


async def test_failed_jobs_listed_and_retryable(app_client: Any) -> None:
    _, token = await make_instance(app_client)
    await post(app_client, token, fx("text_received_mixed"))
    async with app_client.app.state.session_factory() as s:
        await s.execute(update(Job).values(status="failed", last_error="boom"))
        await s.execute(update(Message).values(status="failed"))
        await s.commit()
    jobs = (await app_client.get("/api/jobs")).json()
    assert len(jobs) == 1 and jobs[0]["last_error"] == "boom" and jobs[0]["message_id"] == 1
    assert (await app_client.post(f"/api/jobs/{jobs[0]['id']}/retry")).status_code == 200
    assert (await app_client.post(f"/api/jobs/{jobs[0]['id']}/retry")).status_code == 409
    assert (await app_client.get("/api/jobs")).json() == []
    async with app_client.app.state.session_factory() as s:
        assert (await s.execute(select(Message.status))).scalar_one() == "pending"


async def test_reprocess_enqueues_and_blocks_redacted(app_client: Any) -> None:
    _, token = await make_instance(app_client)
    await post(app_client, token, fx("text_received_mixed"))
    assert (await app_client.post("/api/messages/1/reprocess")).status_code == 200
    async with app_client.app.state.session_factory() as s:
        assert len((await s.execute(select(Job))).scalars().all()) == 2
        await s.execute(update(Message).values(redacted=True))
        await s.commit()
    assert (await app_client.post("/api/messages/1/reprocess")).status_code == 409
    assert (await app_client.post("/api/messages/999/reprocess")).status_code == 404


async def test_jobs_require_auth(app_client: Any) -> None:
    app_client.cookies.clear()
    assert (await app_client.get("/api/jobs")).status_code == 401
