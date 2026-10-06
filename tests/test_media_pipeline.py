import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from sqlalchemy import select

from app.classify.moderation import URL as MOD_URL
from app.config import get_settings
from app.db.models import Classification, Message
from app.jobs import queue
from app.jobs.handlers import Deps
from app.jobs.worker import run_one
from app.providers import Providers
from app.transcription import openai as openai_t
from tests.test_webhooks import fx, post
from tests.test_worker import mod_response

MEDIA = Path(__file__).parent / "fixtures" / "media"
MEDIA_URL = r"https://wa\.x/api/sessions/s/messages/.*/media"
CF_URL = (
    "https://api.cloudflare.com/client/v4/accounts/acc/ai/run/@cf/openai/whisper-large-v3-turbo"
)


async def setup(c: Any) -> tuple[Deps, str]:
    await c.put("/api/settings", json={"settings": {"openai.api_key": "sk-test"}})
    r = await c.post(
        "/api/instances",
        json={
            "kid_name": "Noa",
            "openwa_base_url": "https://wa.x",
            "openwa_instance_id": "s",
            "openwa_api_key": "owa-key",
        },
    )
    token = r.json()["webhook_url"].rsplit("/", 1)[1]
    deps = Deps(
        c.app.state.session_factory, Providers(), get_settings().key_bytes, get_settings().data_dir
    )
    return deps, token


def serve(name: str, ctype: str = "application/octet-stream") -> None:
    respx.get(url__regex=MEDIA_URL).mock(
        return_value=httpx.Response(
            200, content=(MEDIA / name).read_bytes(), headers={"content-type": ctype}
        )
    )


async def run_all(deps: Deps) -> list[str]:
    out = []
    while (job := await queue.claim(deps.session_factory)) is not None:
        out.append(await run_one(job, deps))
    return out


async def the_message(c: Any) -> tuple[Message, list[Classification]]:
    async with c.app.state.session_factory() as s:
        m = (await s.execute(select(Message))).scalar_one()
        cls = (await s.execute(select(Classification).order_by(Classification.id))).scalars().all()
        return m, list(cls)


def mod_inputs() -> list[Any]:
    return [
        json.loads(c.request.content)["input"] for c in respx.calls if str(c.request.url) == MOD_URL
    ]


def no_tmp_left(c: Any) -> bool:
    tmp = get_settings().data_dir / "tmp"
    return not tmp.exists() or not any(tmp.iterdir())


@respx.mock
async def test_image_with_caption_is_moderated_as_text_plus_jpeg(app_client: Any) -> None:
    deps, token = await setup(app_client)
    serve("image.png", "image/png")
    respx.post(MOD_URL).mock(return_value=mod_response())
    await post(app_client, token, fx("image_caption_sent"))
    assert await run_all(deps) == ["done"]
    m, cls = await the_message(app_client)
    assert m.verdict == "safe" and cls[0].input_kind == "text+image"
    (inp,) = mod_inputs()
    assert inp[0] == {"type": "text", "text": "תמונה עם כיתוב"}
    assert inp[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert no_tmp_left(app_client)


@respx.mock
@pytest.mark.parametrize(
    ("fixture", "file"),
    [("image_nocaption_received", "image.png"), ("sticker_received", "sticker.webp")],
)
async def test_image_without_caption_and_sticker_are_image_only(
    app_client: Any, fixture: str, file: str
) -> None:
    deps, token = await setup(app_client)
    serve(file)
    respx.post(MOD_URL).mock(return_value=mod_response())
    await post(app_client, token, fx(fixture))
    assert await run_all(deps) == ["done"]
    _, cls = await the_message(app_client)
    assert cls[0].input_kind == "image"
    assert mod_inputs()[0][0]["type"] == "image_url"


@respx.mock
async def test_voice_note_is_transcribed_stored_searchable_and_moderated(app_client: Any) -> None:
    deps, token = await setup(app_client)
    serve("voice.ogg", "audio/ogg")
    tr = respx.post(openai_t.URL).mock(
        return_value=httpx.Response(200, json={"text": "שלום מהקלטה"})
    )
    respx.post(MOD_URL).mock(return_value=mod_response())
    await post(app_client, token, fx("voice_sent"))
    assert await run_all(deps) == ["done"]
    m, cls = await the_message(app_client)
    assert m.transcript == "שלום מהקלטה" and m.verdict == "safe" and cls[0].input_kind == "text"
    assert mod_inputs() == ["שלום מהקלטה"] and tr.call_count == 1
    found = (await app_client.get("/api/messages", params={"q": "מהקלטה"})).json()
    assert found["total"] == 1 and found["items"][0]["transcript"] == "שלום מהקלטה"
    assert no_tmp_left(app_client)


@respx.mock
async def test_video_with_audio_moderates_transcript_plus_caption(app_client: Any) -> None:
    deps, token = await setup(app_client)
    serve("video_audio.mp4", "video/mp4")
    respx.post(openai_t.URL).mock(return_value=httpx.Response(200, json={"text": "spoken words"}))
    respx.post(MOD_URL).mock(return_value=mod_response())
    await post(app_client, token, fx("video_sent"))  # caption: "video with speech"
    assert await run_all(deps) == ["done"]
    assert mod_inputs() == ["video with speech\nspoken words"]


@respx.mock
async def test_silent_video_without_caption_is_skipped_and_with_caption_moderates_caption(
    app_client: Any,
) -> None:
    deps, token = await setup(app_client)
    serve("video_silent.mp4", "video/mp4")
    tr = respx.post(openai_t.URL).mock(return_value=httpx.Response(200, json={"text": "x"}))
    respx.post(MOD_URL).mock(return_value=mod_response())
    body = json.loads(fx("video_sent"))
    body["data"]["body"] = ""
    await post(app_client, token, json.dumps(body).encode())
    assert await run_all(deps) == ["done"]
    m, _ = await the_message(app_client)
    assert m.status == "skipped" and m.verdict is None and tr.call_count == 0

    # same silent video, now with a caption: the caption alone is moderated
    await app_client.post(f"/api/messages/{m.id}/reprocess")
    async with app_client.app.state.session_factory() as s:
        row = await s.get(Message, m.id)
        assert row
        row.text = "caption only"
        await s.commit()
    assert await run_all(deps) == ["done"]
    assert mod_inputs() == ["caption only"] and tr.call_count == 0


@respx.mock
async def test_empty_transcript_is_skipped(app_client: Any) -> None:
    deps, token = await setup(app_client)
    serve("voice.ogg")
    respx.post(openai_t.URL).mock(return_value=httpx.Response(200, json={"text": "  "}))
    await post(app_client, token, fx("voice_sent"))
    assert await run_all(deps) == ["done"]
    m, _ = await the_message(app_client)
    assert m.status == "skipped" and m.transcript is None


@respx.mock
async def test_audio_over_duration_limit_is_skipped_without_transcribing(
    app_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.jobs.handlers.MAX_AUDIO_SECONDS", 0.5)
    deps, token = await setup(app_client)
    serve("voice.ogg")
    tr = respx.post(openai_t.URL).mock(return_value=httpx.Response(200, json={"text": "x"}))
    await post(app_client, token, fx("voice_sent"))
    assert await run_all(deps) == ["done"]
    m, _ = await the_message(app_client)
    assert m.status == "skipped" and tr.call_count == 0 and no_tmp_left(app_client)


@respx.mock
async def test_oversized_media_is_skipped(app_client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.media.fetch.MAX_MEDIA_BYTES", 100)
    deps, token = await setup(app_client)
    serve("video_audio.mp4")
    await post(app_client, token, fx("video_sent"))
    assert await run_all(deps) == ["done"]
    assert (await the_message(app_client))[0].status == "skipped"


@respx.mock
async def test_media_gone_from_openwa_fails_permanently_and_cleans_up(app_client: Any) -> None:
    deps, token = await setup(app_client)
    respx.get(url__regex=MEDIA_URL).mock(return_value=httpx.Response(404))
    await post(app_client, token, fx("image_caption_sent"))
    assert await run_all(deps) == ["failed"]
    assert (await the_message(app_client))[0].status == "failed" and no_tmp_left(app_client)


@respx.mock
async def test_transcript_survives_a_moderation_retry_without_retranscribing(
    app_client: Any,
) -> None:
    deps, token = await setup(app_client)
    serve("voice.ogg")
    tr = respx.post(openai_t.URL).mock(return_value=httpx.Response(200, json={"text": "kept"}))
    respx.post(MOD_URL).mock(side_effect=[httpx.Response(429), mod_response()])
    await post(app_client, token, fx("voice_sent"))
    job = await queue.claim(deps.session_factory)
    assert job and await run_one(job, deps) == "queued"
    async with app_client.app.state.session_factory() as s:
        from sqlalchemy import update

        from app.db.models import Job

        await s.execute(update(Job).values(run_after=__import__("datetime").datetime(2000, 1, 1)))
        await s.commit()
    assert await run_all(deps) == ["done"]
    assert tr.call_count == 1 and (await the_message(app_client))[0].verdict == "safe"


@respx.mock
async def test_switching_to_cloudflare_takes_effect_without_restart(app_client: Any) -> None:
    deps, token = await setup(app_client)
    await app_client.put(
        "/api/settings",
        json={
            "settings": {
                "transcription.provider": "cloudflare",
                "transcription.cloudflare_account_id": "acc",
                "transcription.cloudflare_api_token": "tok",
            }
        },
    )
    serve("voice.ogg")
    cf = respx.post(CF_URL).mock(
        return_value=httpx.Response(200, json={"result": {"text": "from cf"}})
    )
    oa = respx.post(openai_t.URL).mock(
        return_value=httpx.Response(200, json={"text": "from openai"})
    )
    respx.post(MOD_URL).mock(return_value=mod_response())
    await post(app_client, token, fx("voice_sent"))
    assert await run_all(deps) == ["done"]
    assert cf.call_count == 1 and oa.call_count == 0
    assert (await the_message(app_client))[0].transcript == "from cf"


@respx.mock
async def test_document_only_caption_is_moderated(app_client: Any) -> None:
    deps, token = await setup(app_client)
    respx.post(MOD_URL).mock(return_value=mod_response())
    await post(app_client, token, fx("document_sent"))  # caption "doc"
    assert await run_all(deps) == ["done"]
    assert mod_inputs() == ["doc"]
    assert not any(
        c.request.method == "GET" for c in respx.calls
    )  # the file itself is never fetched
