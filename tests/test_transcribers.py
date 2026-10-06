import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from app.config import get_settings
from app.jobs.queue import PermanentError, TransientError
from app.settings_store import set_setting
from app.transcription import cloudflare, openai
from app.transcription.cloudflare import CloudflareTranscriber
from app.transcription.factory import build_transcriber
from app.transcription.openai import OpenAITranscriber

CF_URL = (
    "https://api.cloudflare.com/client/v4/accounts/acc/ai/run/@cf/openai/whisper-large-v3-turbo"
)


@pytest.fixture
def audio(tmp_path: Path) -> Path:
    p = tmp_path / "a.mp3"
    p.write_bytes(b"ID3fakeaudio")
    return p


@respx.mock
async def test_openai_request_shape_and_result(audio: Path) -> None:
    route = respx.post(openai.URL).mock(
        return_value=httpx.Response(200, json={"text": " שלום עולם "})
    )
    t = OpenAITranscriber("sk-1", "gpt-4o-mini-transcribe")
    res = await t.transcribe(audio, "audio/mpeg")
    req = route.calls.last.request
    assert req.headers["authorization"] == "Bearer sk-1"
    body = req.read()
    assert b'name="model"' in body and b"gpt-4o-mini-transcribe" in body
    assert b'name="response_format"' in body and b"json" in body and b"language" not in body
    assert res.text == "שלום עולם" and res.language is None
    await t.aclose()


@respx.mock
async def test_openai_whisper1_uses_verbose_json_for_language(audio: Path) -> None:
    route = respx.post(openai.URL).mock(
        return_value=httpx.Response(
            200, json={"text": "hi", "language": "english", "duration": 3.5}
        )
    )
    res = await OpenAITranscriber("k", "whisper-1").transcribe(audio, "audio/mpeg")
    assert b"verbose_json" in route.calls.last.request.read()
    assert res.language == "english" and res.duration_seconds == 3.5


@respx.mock
@pytest.mark.parametrize(
    ("status", "exc"),
    [(429, TransientError), (503, TransientError), (400, PermanentError), (401, PermanentError)],
)
async def test_openai_error_mapping(audio: Path, status: int, exc: type[Exception]) -> None:
    respx.post(openai.URL).mock(return_value=httpx.Response(status))
    with pytest.raises(exc):
        await OpenAITranscriber("k", "whisper-1").transcribe(audio, "audio/mpeg")


@respx.mock
async def test_openai_network_and_garbage_are_transient(audio: Path) -> None:
    respx.post(openai.URL).mock(side_effect=httpx.ReadTimeout("t"))
    with pytest.raises(TransientError):
        await OpenAITranscriber("k", "whisper-1").transcribe(audio, "audio/mpeg")
    respx.post(openai.URL).mock(return_value=httpx.Response(200, json={"nope": 1}))
    with pytest.raises(TransientError):
        await OpenAITranscriber("k", "whisper-1").transcribe(audio, "audio/mpeg")


@respx.mock
async def test_cloudflare_request_shape_and_result(audio: Path) -> None:
    route = respx.post(CF_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "result": {
                    "text": "hello",
                    "transcription_info": {"language": "en", "duration": 2.0},
                },
                "success": True,
            },
        )
    )
    res = await CloudflareTranscriber("acc", "tok", "@cf/openai/whisper-large-v3-turbo").transcribe(
        audio, "audio/mpeg"
    )
    req = route.calls.last.request
    assert req.headers["authorization"] == "Bearer tok"
    assert json.loads(req.read())["audio"] == "SUQzZmFrZWF1ZGlv"  # base64 of the file bytes
    assert (res.text, res.language, res.duration_seconds) == ("hello", "en", 2.0)


@respx.mock
async def test_cloudflare_errors(audio: Path) -> None:
    t = CloudflareTranscriber("acc", "tok", "@cf/openai/whisper-large-v3-turbo")
    respx.post(CF_URL).mock(return_value=httpx.Response(429, headers={"retry-after": "7"}))
    with pytest.raises(TransientError) as e:
        await t.transcribe(audio, "audio/mpeg")
    assert e.value.retry_after == 7.0
    respx.post(CF_URL).mock(return_value=httpx.Response(403))
    with pytest.raises(PermanentError):
        await t.transcribe(audio, "audio/mpeg")
    respx.post(CF_URL).mock(return_value=httpx.Response(200, json={"success": True}))
    with pytest.raises(TransientError):
        await t.transcribe(audio, "audio/mpeg")


async def test_factory_switches_provider_without_restart(app_client: Any) -> None:
    key = get_settings().key_bytes
    async with app_client.app.state.session_factory() as db:
        with pytest.raises(PermanentError):  # nothing configured yet
            await build_transcriber(db, key)
        await set_setting(db, "openai.api_key", "sk-x", key)
        assert (await build_transcriber(db, key)).name == "openai"
        await set_setting(db, "transcription.provider", "cloudflare")
        with pytest.raises(PermanentError):
            await build_transcriber(db, key)
        await set_setting(db, "transcription.cloudflare_account_id", "acc")
        await set_setting(db, "transcription.cloudflare_api_token", "tok", key)
        assert (await build_transcriber(db, key)).name == "cloudflare"
    assert cloudflare.CloudflareTranscriber is CloudflareTranscriber


async def test_transcription_settings_validated_and_token_secret(app_client: Any) -> None:
    bad = await app_client.put(
        "/api/settings", json={"settings": {"transcription.provider": "azure"}}
    )
    assert bad.status_code == 422
    ok = await app_client.put(
        "/api/settings",
        json={
            "settings": {
                "transcription.cloudflare_api_token": "tok-secret",
                "transcription.provider": "cloudflare",
            }
        },
    )
    assert ok.json()["transcription.cloudflare_api_token"] == {"set": True}
    assert "tok-secret" not in (await app_client.get("/api/settings")).text
