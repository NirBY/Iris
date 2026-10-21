import json

import httpx
import pytest
import respx

from app.telegram.client import TelegramClient, TelegramError, validate_token

TOKEN = "123456789:AAH-test_token_value_0123456789abc"
URL = f"https://api.telegram.org/bot{TOKEN}/sendMessage"


@respx.mock
async def test_send_text_request_shape() -> None:
    route = respx.post(URL).mock(return_value=httpx.Response(200, json={"ok": True}))
    client = TelegramClient(TOKEN)
    await client.send_text("-1001234567890", "⚠️ Iris alert\nhello")
    await client.aclose()
    body = json.loads(route.calls.last.request.content)
    assert body["chat_id"] == "-1001234567890"
    assert body["text"] == "⚠️ Iris alert\nhello"
    assert "parse_mode" not in body


@respx.mock
async def test_text_is_capped_at_telegram_limit() -> None:
    route = respx.post(URL).mock(return_value=httpx.Response(200, json={"ok": True}))
    client = TelegramClient(TOKEN)
    await client.send_text("1", "x" * 5000)
    await client.aclose()
    assert len(json.loads(route.calls.last.request.content)["text"]) == 4096


@respx.mock
async def test_429_carries_retry_after() -> None:
    respx.post(URL).mock(
        return_value=httpx.Response(
            429,
            json={
                "ok": False,
                "description": "Too Many Requests: retry after 7",
                "parameters": {"retry_after": 7},
            },
        )
    )
    client = TelegramClient(TOKEN)
    with pytest.raises(TelegramError) as err:
        await client.send_text("1", "hi")
    await client.aclose()
    assert err.value.status == 429 and err.value.retry_after == 7.0


@respx.mock
async def test_bad_token_and_bad_chat_surface_description_only() -> None:
    respx.post(URL).mock(
        return_value=httpx.Response(401, json={"ok": False, "description": "Unauthorized"})
    )
    client = TelegramClient(TOKEN)
    with pytest.raises(TelegramError) as err:
        await client.send_text("1", "hi")
    await client.aclose()
    assert err.value.status == 401 and err.value.message == "Unauthorized"
    assert err.value.retry_after is None


@respx.mock
async def test_non_json_error_body_is_not_echoed() -> None:
    respx.post(URL).mock(return_value=httpx.Response(502, text="<html>secret upstream page</html>"))
    client = TelegramClient(TOKEN)
    with pytest.raises(TelegramError) as err:
        await client.send_text("1", "hi")
    await client.aclose()
    assert err.value.status == 502 and err.value.message == "HTTP 502"


@respx.mock
async def test_network_error_has_no_status_and_never_leaks_the_token() -> None:
    respx.post(URL).mock(side_effect=httpx.ConnectError(f"failed for {URL}"))
    client = TelegramClient(TOKEN)
    with pytest.raises(TelegramError) as err:
        await client.send_text("1", "hi")
    await client.aclose()
    assert err.value.status is None
    assert TOKEN not in err.value.message and TOKEN not in str(err.value)


@pytest.mark.parametrize(
    "bad",
    ["", "nope", "123456:short", "abc:AAH-test_token_value_0123456789abc", f"{TOKEN}/../x"],
)
def test_invalid_tokens_are_rejected_before_any_request(bad: str) -> None:
    with pytest.raises(ValueError):
        TelegramClient(bad)


def test_surrounding_whitespace_in_a_token_is_trimmed() -> None:
    assert validate_token(f"  {TOKEN}\n") == TOKEN
