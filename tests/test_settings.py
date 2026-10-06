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


async def test_openai_test_button_uses_entered_key_and_reports_errors(app_client: Any) -> None:
    import httpx
    import respx

    from app.classify.moderation import URL

    ok = {"results": [{"flagged": False, "categories": {}, "category_scores": {"hate": 0.0}}]}
    with respx.mock:
        route = respx.post(URL).mock(return_value=httpx.Response(200, json=ok))
        r = await app_client.post("/api/settings/test/openai", json={"api_key": "sk-typed"})
        assert r.json()["ok"] is True
        assert route.calls.last.request.headers["authorization"] == "Bearer sk-typed"
        route.mock(return_value=httpx.Response(401))
        bad = (
            await app_client.post("/api/settings/test/openai", json={"api_key": "sk-bad"})
        ).json()
        assert bad["ok"] is False and "401" in bad["detail"] and "sk-bad" not in str(bad)
    assert (await app_client.post("/api/settings/test/openai")).json() == {
        "ok": False,
        "detail": "No OpenAI API key set",
    }


async def test_cloudflare_test_button_transcribes_bundled_silence(app_client: Any) -> None:
    import httpx
    import respx

    url = (
        "https://api.cloudflare.com/client/v4/accounts/acc/ai/run/@cf/openai/whisper-large-v3-turbo"
    )
    form = {"account_id": "acc", "api_token": "tok"}
    with respx.mock:
        route = respx.post(url).mock(
            return_value=httpx.Response(200, json={"result": {"text": ""}})
        )
        r = (await app_client.post("/api/settings/test/cloudflare", json=form)).json()
        assert r["ok"] is True and route.call_count == 1
        assert len(route.calls.last.request.content) > 10_000  # the 1-second wav, base64
        route.mock(return_value=httpx.Response(403))
        assert (await app_client.post("/api/settings/test/cloudflare", json=form)).json()[
            "ok"
        ] is False
    missing = (await app_client.post("/api/settings/test/cloudflare")).json()
    assert missing["ok"] is False and "required" in missing["detail"]


async def test_alert_test_not_implemented_yet_and_unknown_target(app_client: Any) -> None:
    assert (await app_client.post("/api/settings/test/alert")).status_code == 501
    assert (await app_client.post("/api/settings/test/nope")).status_code == 422
