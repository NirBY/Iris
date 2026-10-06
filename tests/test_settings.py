from typing import Any

from sqlalchemy import select

from app.config import get_settings
from app.db.models import Setting
from app.settings_store import get_secret, get_setting


async def test_defaults_and_secret_reported_as_set_flag(app_client: Any) -> None:
    s = (await app_client.get("/api/settings")).json()
    assert s["classification.model"] == "omni-moderation-latest"
    assert s["classification.context_window_size"] == 8
    assert s["openai.api_key"] == {"set": False}


async def test_secret_is_encrypted_write_only_and_round_trips(app_client: Any) -> None:
    r = await app_client.put("/api/settings", json={"settings": {"openai.api_key": "sk-live-123"}})
    assert r.status_code == 200 and r.json()["openai.api_key"] == {"set": True}
    assert "sk-live-123" not in (await app_client.get("/api/settings")).text
    async with app_client.app.state.session_factory() as s:
        row = (await s.execute(select(Setting).where(Setting.key == "openai.api_key"))).scalar_one()
        assert row.is_secret and "sk-live-123" not in str(row.value)
        assert await get_secret(s, "openai.api_key", get_settings().key_bytes) == "sk-live-123"


async def test_validation_errors_apply_nothing(app_client: Any) -> None:
    r = await app_client.put(
        "/api/settings",
        json={
            "settings": {
                "classification.model": "m2",
                "classification.context_window_size": 99,
                "nope": 1,
            }
        },
    )
    assert r.status_code == 422
    assert set(r.json()["detail"]) == {"classification.context_window_size", "nope"}
    async with app_client.app.state.session_factory() as s:
        assert await get_setting(s, "classification.model") == "omni-moderation-latest"


async def test_thresholds_validated(app_client: Any) -> None:
    bad = {"classification.thresholds": {"violence": {"low": 0.9, "high": 0.2}}}
    assert (await app_client.put("/api/settings", json={"settings": bad})).status_code == 422
    good = {"classification.thresholds": {"violence": {"low": 0.3, "high": 0.8}}}
    assert (await app_client.put("/api/settings", json={"settings": good})).status_code == 200


async def test_settings_require_auth(app_client: Any) -> None:
    app_client.cookies.clear()
    assert (await app_client.get("/api/settings")).status_code == 401


async def test_secret_can_be_cleared_and_thresholds_are_normalised(app_client: Any) -> None:
    await app_client.put("/api/settings", json={"settings": {"openai.api_key": "sk-1"}})
    r = await app_client.put("/api/settings", json={"settings": {"openai.api_key": ""}})
    assert r.json()["openai.api_key"] == {"set": False}
    t = {"classification.thresholds": {"violence": {"low": "0.3", "high": 0.8}}}
    r = await app_client.put("/api/settings", json={"settings": t})
    assert r.json()["classification.thresholds"] == {"violence": {"low": 0.3, "high": 0.8}}
