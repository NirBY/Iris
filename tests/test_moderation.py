import httpx
import pytest
import respx

from app.classify.moderation import URL, ModerationClient
from app.jobs.queue import PermanentError, TransientError

OK = {
    "model": "omni-moderation-latest",
    "results": [
        {
            "flagged": True,
            "categories": {"violence": True, "hate": False},
            "category_scores": {"violence": 0.91, "hate": 0.01},
            "category_applied_input_types": {"violence": ["text"], "hate": ["text"]},
        }
    ],
}


@respx.mock
async def test_text_request_and_parse() -> None:
    route = respx.post(URL).mock(return_value=httpx.Response(200, json=OK))
    c = ModerationClient("sk-test")
    res = await c.moderate("omni-moderation-latest", "hello")
    assert route.calls.last.request.headers["authorization"] == "Bearer sk-test"
    assert route.calls.last.request.read() == b'{"model":"omni-moderation-latest","input":"hello"}'
    assert res.scores["violence"] == 0.91 and res.flagged
    stored = res.stored_scores()
    assert stored["violence"] == 0.91 and stored["_meta"]["applied_input_types"]["hate"] == ["text"]
    await c.aclose()


@respx.mock
@pytest.mark.parametrize("status", [429, 500, 503])
async def test_transient_statuses_with_retry_after(status: int) -> None:
    respx.post(URL).mock(return_value=httpx.Response(status, headers={"retry-after": "42"}))
    with pytest.raises(TransientError) as e:
        await ModerationClient("k").moderate("m", "x")
    assert e.value.retry_after == 42.0


@respx.mock
@pytest.mark.parametrize("status", [400, 401, 403])
async def test_permanent_statuses(status: int) -> None:
    respx.post(URL).mock(return_value=httpx.Response(status))
    with pytest.raises(PermanentError):
        await ModerationClient("k").moderate("m", "x")


@respx.mock
async def test_network_error_and_garbage_are_transient() -> None:
    respx.post(URL).mock(side_effect=httpx.ConnectTimeout("t"))
    with pytest.raises(TransientError):
        await ModerationClient("k").moderate("m", "x")
    respx.post(URL).mock(return_value=httpx.Response(200, json={"results": []}))
    with pytest.raises(TransientError):
        await ModerationClient("k").moderate("m", "x")
