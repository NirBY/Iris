"""Real OpenAI Moderation calls. Run `pytest -m integration` (needs TEST_OPENAI_API_KEY)."""

import os

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
