import json

import httpx
import pytest
import respx

from app.classify.ollama import OllamaModerator
from app.classify.thresholds import DEFAULT_THRESHOLDS
from app.jobs.queue import PermanentError, TransientError
from app.transcription.whisper import WhisperTranscriber


@pytest.mark.parametrize(
    "bad",
    [
        {},
        {"violence": 0},
        {k: True for k in DEFAULT_THRESHOLDS},
        {k: 2 for k in DEFAULT_THRESHOLDS},
    ],
)
@respx.mock
async def test_invalid_local_scores_never_become_safe(bad):
    respx.post("http://ollama/api/chat").mock(
        return_value=httpx.Response(200, json={"message": {"content": json.dumps(bad)}})
    )
    client = OllamaModerator("http://ollama", "model")
    try:
        with pytest.raises(TransientError):
            await client.moderate("", "test")
    finally:
        await client.aclose()


async def test_unvalidated_images_are_not_marked_safe():
    client = OllamaModerator("http://ollama", "model")
    try:
        with pytest.raises(PermanentError):
            await client.moderate("", [{"type": "image_url"}])
    finally:
        await client.aclose()


@respx.mock
async def test_local_transcription_auth_model_and_invalid_output(tmp_path):
    path = tmp_path / "sample.mp3"
    path.write_bytes(b"test audio")
    route = respx.post("http://mac/v1/audio/transcriptions").mock(
        return_value=httpx.Response(200, json={"text": None})
    )
    client = WhisperTranscriber("http://mac/v1/audio/transcriptions", "test-token", "auto")
    try:
        with pytest.raises(TransientError):
            await client.transcribe(path, "audio/mpeg")
        request = route.calls[0].request
        assert request.headers["Authorization"] == "Bearer test-token"
        assert b"auto" in request.content
    finally:
        await client.aclose()


@respx.mock
async def test_auto_rejection_retries_local_hebrew_model_once(tmp_path):
    path = tmp_path / "sample.wav"
    path.write_bytes(b"audio")
    route = respx.post("http://mac/v1/audio/transcriptions").mock(
        side_effect=[
            httpx.Response(422, json={"detail": "Local transcription failed"}),
            httpx.Response(200, json={"text": "תודה רבה"}),
        ]
    )
    client = WhisperTranscriber("http://mac/v1/audio/transcriptions")
    try:
        result = await client.transcribe(path, "audio/wav")
        assert result.text == "תודה רבה"
        assert len(route.calls) == 2
        assert b"ivrit-large-v3" in route.calls[1].request.content
    finally:
        await client.aclose()
