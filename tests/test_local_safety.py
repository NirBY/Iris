"""Regression cases for the opt-in safety mode, with no real child data or sends."""

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
import respx
from sqlalchemy import select

from app.classify.moderation import URL, ModerationResult
from app.classify.ollama import OllamaModerator
from app.config import Settings, get_settings
from app.db.models import Job, Message, MessageRevision
from app.jobs import queue
from app.jobs.queue import PermanentError
from tests.test_queue import factory  # noqa: F401
from tests.test_webhooks import fx, post
from tests.test_worker import drain, mod_response, setup


def enable(monkeypatch: pytest.MonkeyPatch, local: bool = False) -> None:
    monkeypatch.setenv("IRIS_LOCAL_SAFETY_MODE", "true")
    if local:
        monkeypatch.setenv("IRIS_CLASSIFICATION_PROVIDER", "ollama")
    get_settings.cache_clear()


def test_defaults_preserve_upstream_and_do_not_select_local_services() -> None:
    cfg = Settings(_env_file=None)  # type: ignore[call-arg]
    assert cfg.classification_provider == "openai" and cfg.whisper_url is None
    assert not cfg.local_safety_mode and cfg.delivery_workers == 0
    assert cfg.job_heartbeat_seconds == 0 and cfg.whisper_fallback_model is None


@respx.mock
@pytest.mark.parametrize("caption", [None, "have a good day", "I will kill you"])
async def test_local_images_review_without_losing_harmful_caption(
    app_client: Any, monkeypatch: pytest.MonkeyPatch, caption: str | None
) -> None:
    enable(monkeypatch, local=True)
    seen: list[str] = []

    async def moderate(self: Any, model: str, body: str) -> ModerationResult:
        assert isinstance(body, str)
        seen.append(body)
        return ModerationResult({"violence": 0.99 if "kill" in body else 0.0}, False, {})

    monkeypatch.setattr(OllamaModerator, "moderate", moderate)
    deps, token = await setup(app_client)
    import json

    body = json.loads(fx("image_caption_sent"))
    body["data"]["body"] = caption or ""
    await post(app_client, token, json.dumps(body).encode())
    assert await drain(deps) == ["done"]
    async with deps.session_factory() as db:
        message = (await db.scalars(select(Message))).one()
        assert message.status == "done"
        assert message.verdict == ("harmful" if caption and "kill" in caption else "review")
    assert seen == ([caption] if caption else [])
    await deps.providers.aclose()


@respx.mock
async def test_edit_before_classification_preserves_original_harm(
    app_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    enable(monkeypatch)
    deps, token = await setup(app_client)
    respx.post(URL).mock(side_effect=[mod_response(), mod_response(violence=0.99)])
    await post(app_client, token, fx("text_received_mixed"))
    async with deps.session_factory() as db:
        message = (await db.scalars(select(Message))).one()
        db.add(MessageRevision(message_id=message.id, text="I will kill you"))
        message.text = "ok"
        message.edited_at = datetime.now(UTC)
        await db.commit()
    assert await drain(deps) == ["done"]
    async with deps.session_factory() as db:
        message = (await db.scalars(select(Message))).one()
        assert message.verdict == "harmful" and message.text == "ok"
    await deps.providers.aclose()


async def test_delivery_lane_and_lease_renewal(factory: Any) -> None:  # noqa: F811
    async with factory() as db:
        await queue.enqueue(db, "process_message", {"message_id": 99})
        alert_id = await queue.enqueue(db, "deliver_alert", {"alert_id": 99})
    delivery = await queue.claim(factory, types=("deliver_alert", "notify_change"))
    assert delivery and delivery.id == alert_id
    regular = await queue.claim(factory, exclude_types=("deliver_alert", "notify_change"))
    assert regular and regular.type == "process_message"
    async with factory() as db:
        row = await db.get(Job, regular.id)
        row.locked_at = datetime.now(UTC) - timedelta(minutes=11)
        await db.commit()
    await queue.heartbeat(factory, regular)
    assert await queue.recover_stale(factory) == 0


@respx.mock
async def test_local_provider_metadata_and_authenticated_test_button(
    app_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("IRIS_WHISPER_URL", "http://mac.test:8081/v1/audio/transcriptions")
    monkeypatch.setenv("IRIS_WHISPER_API_KEY", "private-test-key")
    get_settings.cache_clear()
    data = (await app_client.get("/api/settings")).json()
    assert data["local_providers"]["transcription"] == "local_whisper"
    assert "private-test-key" not in str(data)
    route = respx.get("http://mac.test:8081/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "auto"}]})
    )
    result = await app_client.post("/api/settings/test/local_whisper", json={})
    assert result.json()["ok"]
    assert route.calls.last.request.headers["Authorization"] == "Bearer private-test-key"
    route.mock(return_value=httpx.Response(401))
    assert not (await app_client.post("/api/settings/test/local_whisper", json={})).json()["ok"]


@respx.mock
async def test_unprocessable_voice_is_reviewed_not_failed(
    app_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.jobs import handlers

    enable(monkeypatch)
    deps, token = await setup(app_client)

    async def unavailable(*args: Any) -> None:
        raise PermanentError("transcription HTTP 422")

    monkeypatch.setattr(handlers, "_transcribe", unavailable)
    await post(app_client, token, fx("voice_sent"))
    assert await drain(deps) == ["done"]
    async with deps.session_factory() as db:
        message = (await db.scalars(select(Message))).one()
        assert message.verdict == "review" and message.status == "done"


@respx.mock
async def test_partial_delivery_is_visible_and_notified(
    app_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json

    from tests.test_alerts import SEND_URL, alerts, run_all
    from tests.test_alerts import setup as alert_setup

    enable(monkeypatch)
    deps, token, _ = await alert_setup(app_client, recipient="15550100101, 15550100102")
    respx.post(URL).mock(return_value=mod_response(violence=0.99))

    def send(request: httpx.Request) -> httpx.Response:
        target = json.loads(request.content)["chatId"]
        return httpx.Response(
            400 if target == "15550100101@c.us" else 201, json={"message": "rejected", "id": "sent"}
        )

    respx.post(SEND_URL).mock(side_effect=send)
    await post(app_client, token, fx("text_received_mixed"))
    await run_all(deps)
    alert = (await alerts(app_client))[0]
    assert alert.delivery_status == "partial" and alert.notified_at is not None


@respx.mock
async def test_monitoring_checks_sender_even_when_not_monitored(app_client: Any) -> None:
    from app.monitoring import probe_sessions, states
    from tests.test_alerts import setup as alert_setup

    deps, _, sender_id = await alert_setup(app_client)
    async with deps.session_factory() as db:
        from app.db.models import Instance

        sender = await db.get(Instance, sender_id)
        sender.enabled = False
        await db.commit()
    # The fixture's parent session id is taken from the DB, not assumed.
    async with deps.session_factory() as db:
        sender = await db.get(Instance, sender_id)
        url = f"{sender.openwa_base_url}/api/sessions/{sender.openwa_instance_id}"
        for instance in (await db.scalars(select(Instance))).all():
            respx.get(
                f"{instance.openwa_base_url}/api/sessions/{instance.openwa_instance_id}"
            ).mock(return_value=httpx.Response(200, json={"data": {"status": "ready"}}))
    route = respx.get(url).mock(
        return_value=httpx.Response(200, json={"data": {"status": "ready"}})
    )
    await probe_sessions(deps.session_factory, deps.key_bytes)
    assert states[sender_id]
    route.mock(return_value=httpx.Response(200, json={"status": "disconnected"}))
    await probe_sessions(deps.session_factory, deps.key_bytes)
    assert not states[sender_id]


async def test_global_signature_requirement_rejects_unsigned_before_registration(
    app_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    import hashlib
    import hmac

    from app.api.instances import webhook_secret
    from tests.test_webhooks import make_instance

    monkeypatch.setenv("IRIS_REQUIRE_WEBHOOK_SIGNATURES", "true")
    get_settings.cache_clear()
    _, token = await make_instance(app_client)
    raw = fx("text_received_mixed")
    assert (await post(app_client, token, raw)).status_code == 401
    good = (
        "sha256="
        + hmac.new(webhook_secret(get_settings(), token).encode(), raw, hashlib.sha256).hexdigest()
    )
    assert (await post(app_client, token, raw, **{"x-openwa-signature": good})).status_code == 200


async def test_saved_choices_override_environment_and_reload_after_restart(
    app_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.settings_store import reload_runtime_settings
    from app.transcription.factory import build_transcriber

    monkeypatch.setenv("IRIS_CLASSIFICATION_PROVIDER", "ollama")
    monkeypatch.setenv("IRIS_WHISPER_URL", "http://mac.test/v1/audio/transcriptions")
    get_settings.cache_clear()
    response = await app_client.put(
        "/api/settings",
        json={
            "settings": {
                "runtime.classification_provider": "openai",
                "runtime.transcription_provider": "openai",
                "openai.api_key": "test-cloud-key",
                "runtime.local_safety_mode": True,
                "runtime.ollama_model": "selected-test-model",
            }
        },
    )
    assert response.status_code == 200
    assert get_settings().classification_provider == "openai"
    async with app_client.app.state.session_factory() as db:
        transcriber = await build_transcriber(db, get_settings().key_bytes)
        assert transcriber.name == "openai"
        await transcriber.aclose()
        get_settings.cache_clear()  # a fresh environment-only bootstrap
        assert get_settings().classification_provider == "ollama"
        await reload_runtime_settings(db)
    assert get_settings().classification_provider == "openai"
    assert get_settings().ollama_model == "selected-test-model"
    assert get_settings().local_safety_mode


async def test_endpoint_change_requires_key_and_secret_is_never_returned(
    app_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("IRIS_WHISPER_URL", "http://old.test/v1/audio/transcriptions")
    monkeypatch.setenv("IRIS_WHISPER_API_KEY", "old-test-key")
    get_settings.cache_clear()
    changed = {"runtime.whisper_url": "http://new.test/v1/audio/transcriptions"}
    assert (await app_client.put("/api/settings", json={"settings": changed})).status_code == 422
    changed["runtime.whisper_api_key"] = "new-test-key"
    response = await app_client.put("/api/settings", json={"settings": changed})
    assert response.status_code == 200 and "new-test-key" not in response.text
    assert get_settings().whisper_api_key == "new-test-key"
    response = await app_client.put(
        "/api/settings",
        json={
            "settings": {
                "runtime.whisper_api_key": None,
                "runtime.whisper_use_environment_key": False,
            }
        },
    )
    assert response.status_code == 200 and get_settings().whisper_api_key is None


async def test_worker_resize_does_not_cancel_inflight_job(
    factory: Any,  # noqa: F811
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,  # noqa: F811
) -> None:
    import asyncio

    from app.jobs.handlers import Deps
    from app.jobs.worker import HANDLERS, WorkerPool
    from app.providers import Providers

    started, release, finished = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def held(job: Any, deps: Any) -> None:
        started.set()
        await release.wait()
        finished.set()

    monkeypatch.setitem(HANDLERS, "process_message", held)
    deps = Deps(factory, Providers(), get_settings().key_bytes, data_dir=tmp_path)
    async with factory() as db:
        await queue.enqueue(db, "process_message", {"message_id": 99})
    pool = WorkerPool(deps, 1, poll_interval=0.02)
    await pool.start()
    try:
        await asyncio.wait_for(started.wait(), 5)
        await pool.reconfigure(2, 1)
        assert not finished.is_set() and pool.size == 3
        release.set()
        await asyncio.wait_for(finished.wait(), 5)
    finally:
        release.set()
        await pool.stop()
