import json
from datetime import datetime
from typing import Any

import httpx
import respx
from loguru import logger
from sqlalchemy import select, update

from app.classify.moderation import URL as MOD_URL
from app.db.models import Job
from tests.test_alerts import SEND_URL, alerts, msg_body, run_all, setup
from tests.test_webhooks import fx, post
from tests.test_worker import mod_response

TOKEN = "123456789:AAH-test_token_value_0123456789abc"
TG_URL = f"https://api.telegram.org/bot{TOKEN}/sendMessage"


async def use_telegram(c: Any, chat_id: str | None = "-1001234567890") -> None:
    settings: dict[str, Any] = {"alerts.channel": "telegram", "alerts.telegram_bot_token": TOKEN}
    if chat_id:
        settings["alerts.telegram_chat_id"] = chat_id
    assert (await c.put("/api/settings", json={"settings": settings})).status_code == 200


@respx.mock
async def test_alert_goes_to_telegram_and_not_to_openwa(app_client: Any) -> None:
    deps, token, _ = await setup(app_client)  # WhatsApp is configured too, but ignored
    await use_telegram(app_client)
    respx.post(MOD_URL).mock(return_value=mod_response(violence=0.95))
    whatsapp = respx.post(SEND_URL).mock(return_value=httpx.Response(201, json={}))
    telegram = respx.post(TG_URL).mock(return_value=httpx.Response(200, json={"ok": True}))
    await post(app_client, token, fx("text_received_mixed"))
    assert await run_all(deps) == ["done", "done"]
    (a,) = await alerts(app_client)
    assert a.delivery_status == "sent" and a.notified_at
    assert not whatsapp.called and telegram.call_count == 1
    sent = json.loads(telegram.calls.last.request.content)
    assert sent["chat_id"] == "-1001234567890" and "parse_mode" not in sent
    assert sent["text"].startswith("⚠️ Iris alert\nKid: Noa\n")
    assert f"Open: http://localhost:8080/alerts/{a.id}?s=" in sent["text"]
    await deps.providers.aclose()


@respx.mock
async def test_telegram_cooldown_suppresses_and_resend_bypasses_it(app_client: Any) -> None:
    deps, token, _ = await setup(app_client)
    await use_telegram(app_client)
    respx.post(MOD_URL).mock(return_value=mod_response(violence=0.95))
    telegram = respx.post(TG_URL).mock(return_value=httpx.Response(200, json={"ok": True}))
    for i, h in enumerate(("TG01", "TG02")):
        await post(app_client, token, msg_body("text_received_mixed", h, f"threat {i}", i))
        await run_all(deps)
    a1, a2 = await alerts(app_client)
    assert (a1.delivery_status, a2.delivery_status) == ("sent", "suppressed")
    assert telegram.call_count == 1
    assert (await app_client.post(f"/api/alerts/{a2.id}/resend")).status_code == 200
    await run_all(deps)
    assert (await alerts(app_client))[1].delivery_status == "sent" and telegram.call_count == 2
    await deps.providers.aclose()


@respx.mock
async def test_telegram_rate_limit_is_retried_with_its_retry_after(app_client: Any) -> None:
    deps, token, _ = await setup(app_client)
    await use_telegram(app_client)
    respx.post(MOD_URL).mock(return_value=mod_response(violence=0.95))
    respx.post(TG_URL).mock(
        return_value=httpx.Response(
            429, json={"ok": False, "description": "Too Many", "parameters": {"retry_after": 600}}
        )
    )
    await post(app_client, token, fx("text_received_mixed"))
    await run_all(deps)
    async with app_client.app.state.session_factory() as s:
        job = (await s.execute(select(Job).where(Job.type == "deliver_alert"))).scalar_one()
        assert job.status == "queued" and job.attempts == 1
        assert job.run_after is not None
        assert (job.run_after - datetime.now(job.run_after.tzinfo)).total_seconds() > 300
    assert (await alerts(app_client))[0].delivery_status == "pending"
    await deps.providers.aclose()


@respx.mock
async def test_telegram_server_error_is_retried_then_marked_failed(app_client: Any) -> None:
    deps, token, _ = await setup(app_client)
    await use_telegram(app_client)
    respx.post(MOD_URL).mock(return_value=mod_response(violence=0.95))
    respx.post(TG_URL).mock(
        return_value=httpx.Response(502, json={"ok": False, "description": "Bad Gateway"})
    )
    await post(app_client, token, fx("text_received_mixed"))
    await run_all(deps)
    for _ in range(2):
        async with app_client.app.state.session_factory() as s:
            await s.execute(
                update(Job).where(Job.status == "queued").values(run_after=datetime(2000, 1, 1))
            )
            await s.commit()
        await run_all(deps)
    (a,) = await alerts(app_client)
    assert a.delivery_status == "failed" and "Bad Gateway" in (a.delivery_error or "")
    await deps.providers.aclose()


@respx.mock
async def test_telegram_rejection_fails_at_once_and_resend_works_after_fixing(
    app_client: Any,
) -> None:
    deps, token, _ = await setup(app_client)
    await use_telegram(app_client)
    respx.post(MOD_URL).mock(return_value=mod_response(violence=0.95))
    route = respx.post(TG_URL).mock(
        return_value=httpx.Response(
            400, json={"ok": False, "description": "Bad Request: chat not found"}
        )
    )
    await post(app_client, token, fx("text_received_mixed"))
    await run_all(deps)
    (a,) = await alerts(app_client)
    assert a.delivery_status == "failed" and "chat not found" in (a.delivery_error or "")
    assert TOKEN not in (a.delivery_error or "")
    route.mock(return_value=httpx.Response(200, json={"ok": True}))
    assert (await app_client.post(f"/api/alerts/{a.id}/resend")).status_code == 200
    await run_all(deps)
    assert (await alerts(app_client))[0].delivery_status == "sent"
    await deps.providers.aclose()


@respx.mock
async def test_telegram_selected_but_incomplete_is_not_configured_even_if_whatsapp_is(
    app_client: Any,
) -> None:
    deps, token, _ = await setup(app_client)  # a complete WhatsApp setup
    await use_telegram(app_client, chat_id=None)  # token, but no chat id
    respx.post(MOD_URL).mock(return_value=mod_response(violence=0.95))
    whatsapp = respx.post(SEND_URL).mock(return_value=httpx.Response(201, json={}))
    await post(app_client, token, fx("text_received_mixed"))
    assert await run_all(deps) == ["done"]  # nothing was queued for delivery
    (a,) = await alerts(app_client)
    assert a.delivery_status == "failed" and a.delivery_error == "alert delivery not configured"
    assert not whatsapp.called
    stats = (await app_client.get("/api/stats")).json()
    assert stats["delivery_configured"] is False
    await deps.providers.aclose()


async def test_stats_delivery_configured_follows_the_selected_channel(app_client: Any) -> None:
    await setup(app_client, recipient=None)  # WhatsApp incomplete
    assert (await app_client.get("/api/stats")).json()["delivery_configured"] is False
    await use_telegram(app_client)
    assert (await app_client.get("/api/stats")).json()["delivery_configured"] is True
    await app_client.put("/api/settings", json={"settings": {"alerts.channel": "whatsapp"}})
    assert (await app_client.get("/api/stats")).json()["delivery_configured"] is False


@respx.mock
async def test_telegram_alert_for_sexual_minors_withholds_the_content(app_client: Any) -> None:
    deps, token, _ = await setup(app_client)
    await use_telegram(app_client)
    secret = "SECRETEXPLICITWORDS"
    respx.post(MOD_URL).mock(return_value=mod_response(**{"sexual/minors": 0.9}))
    telegram = respx.post(TG_URL).mock(return_value=httpx.Response(200, json={"ok": True}))
    logs: list[str] = []
    sink = logger.add(lambda m: logs.append(str(m)), level="DEBUG")
    try:
        await post(app_client, token, msg_body("text_received_mixed", "TG99", secret))
        await run_all(deps)
    finally:
        logger.remove(sink)
    text = json.loads(telegram.calls.last.request.content)["text"]
    assert secret not in text and "Content withheld (sexual content)" in text
    assert not any(secret in line or TOKEN in line for line in logs)
    await deps.providers.aclose()
