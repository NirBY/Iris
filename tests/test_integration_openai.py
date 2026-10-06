"""Real OpenAI Moderation calls. Run `pytest -m integration` (needs TEST_OPENAI_API_KEY)."""

import os
from pathlib import Path

import pytest

from app.classify.moderation import ModerationClient
from app.classify.thresholds import DEFAULT_THRESHOLDS, band_for

pytestmark = pytest.mark.integration
KEY = os.environ.get("TEST_OPENAI_API_KEY")


@pytest.mark.skipif(not KEY, reason="TEST_OPENAI_API_KEY not set")
async def test_real_moderation_hebrew_and_english_benign_and_threat() -> None:
    assert KEY
    client = ModerationClient(KEY)
    try:
        for benign in (
            "שלום, מה שלומך? נתראה מחר בבית הספר",
            "See you at football practice tomorrow",
        ):
            res = await client.moderate("omni-moderation-latest", benign)
            assert len(res.scores) == 13
            assert band_for(res.scores, DEFAULT_THRESHOLDS)[0] == "safe"
        threat = await client.moderate(
            "omni-moderation-latest", "I am going to find you and kill you tonight"
        )
        band, high, _ = band_for(threat.scores, DEFAULT_THRESHOLDS)
        assert band == "harmful" and any(c.startswith(("violence", "harassment")) for c in high)
    finally:
        await client.aclose()


@pytest.mark.skipif(not KEY, reason="TEST_OPENAI_API_KEY not set")
@pytest.mark.parametrize("model", ["gpt-4o-mini-transcribe", "whisper-1"])
async def test_real_transcription_of_spoken_english(tmp_path: Path, model: str) -> None:
    import asyncio
    import shutil

    from app.media import ffmpeg
    from app.transcription.openai import OpenAITranscriber

    if not shutil.which("espeak"):
        pytest.skip("espeak not installed")
    assert KEY
    wav, mp3 = tmp_path / "s.wav", tmp_path / "s.mp3"
    proc = await asyncio.create_subprocess_exec(
        "espeak",
        "-v",
        "en",
        "-s",
        "140",
        "Hello, this is a harmless Iris test message.",
        "-w",
        str(wav),
    )
    await proc.wait()
    await ffmpeg.extract_audio(wav, mp3)
    t = OpenAITranscriber(KEY, model)
    try:
        res = await t.transcribe(mp3, "audio/mpeg")
    finally:
        await t.aclose()
    assert "iris" in res.text.lower() and "harmless" in res.text.lower()
