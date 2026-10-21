import json
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
import respx
from sqlalchemy import select

from app.alerts.recipients import recipients
from app.classify.moderation import URL as MOD_URL
from app.db.models import Job
from tests.test_alerts import SEND_URL, alerts, run_all, setup
from tests.test_webhooks import fx, post
from tests.test_worker import mod_response


def test_deduplicate_equivalent_parent_numbers():
    assert recipients("+1 5550100101, 15550100101@c.us\n15550100102") == [
        "15550100101@c.us",
        "15550100102@c.us",
    ]


@pytest.mark.parametrize("value", ["not-a-phone", "15550100101, broken", "123"])
def test_invalid_recipient_rejects_entire_list(value):
    with pytest.raises(ValueError):
        recipients(value)


@respx.mock
async def test_retry_only_failed_parent_and_preserves_target_snapshot(app_client: Any):
    deps, token, _ = await setup(app_client, recipient="15550100101, 15550100102")
    respx.post(MOD_URL).mock(return_value=mod_response(violence=0.95))
    delivered: list[str] = []
    fail_second = True

    def send(request: httpx.Request):
        target = json.loads(request.content)["chatId"]
        if target == "15550100102@c.us" and fail_second:
            return httpx.Response(503, json={"message": "engine busy"})
        delivered.append(target)
        return httpx.Response(201, json={"id": "sent"})

    respx.post(SEND_URL).mock(side_effect=send)
    await post(app_client, token, fx("text_received_mixed"))
    await run_all(deps)
    assert delivered == ["15550100101@c.us"]
    async with deps.session_factory() as db:
        job = (await db.scalars(select(Job).where(Job.type == "deliver_alert"))).one()
        assert job.payload["delivered_recipients"] == ["15550100101@c.us"]
        job.run_after = datetime.now(UTC) - timedelta(seconds=1)
        await db.commit()
    # Editing the setting during a retry must not add a new, unintended recipient.
    await app_client.put("/api/settings", json={"settings": {"alerts.recipient": "15550100103"}})
    fail_second = False
    await run_all(deps)
    assert delivered == ["15550100101@c.us", "15550100102@c.us"]
    assert (await alerts(app_client))[0].delivery_status == "sent"


@respx.mock
async def test_rejected_first_parent_does_not_block_second(app_client: Any):
    deps, token, _ = await setup(app_client, recipient="15550100101, 15550100102")
    respx.post(MOD_URL).mock(return_value=mod_response(violence=0.95))
    targets: list[str] = []

    def send(request: httpx.Request):
        target = json.loads(request.content)["chatId"]
        targets.append(target)
        return httpx.Response(
            400 if target == "15550100101@c.us" else 201,
            json={"message": "Recipient unavailable", "id": "sent"},
        )

    respx.post(SEND_URL).mock(side_effect=send)
    await post(app_client, token, fx("text_received_mixed"))
    await run_all(deps)
    assert targets == ["15550100101@c.us", "15550100102@c.us"]
    assert (await alerts(app_client))[0].delivery_status == "failed"


@respx.mock
async def test_test_button_sends_to_each_unique_parent(app_client: Any):
    _, _, sender_id = await setup(app_client)
    send = respx.post(SEND_URL).mock(return_value=httpx.Response(201, json={"id": "sent"}))
    response = await app_client.post(
        "/api/settings/test/alert",
        json={
            "sender_instance_id": sender_id,
            "recipient": "+15550100101, 15550100101@c.us, 15550100102",
        },
    )
    assert response.json() == {"ok": True, "detail": "Test message sent to 2 parents"}
    assert [json.loads(call.request.content)["chatId"] for call in send.calls] == [
        "15550100101@c.us",
        "15550100102@c.us",
    ]
