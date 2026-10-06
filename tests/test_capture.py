import hashlib
import hmac
import json
from pathlib import Path

import httpx
import pytest

from app import main


def _assert_saved(tmp_path: Path) -> None:
    (f,) = tmp_path.glob("*-kid-a.json")
    saved = json.loads(f.read_text())
    assert saved["signature_valid"] is True
    assert saved["body"]["text"] == "שלום"


async def test_capture_stores_payload_and_checks_signature(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("IRIS_CAPTURE_DIR", str(tmp_path))
    monkeypatch.setenv("IRIS_CAPTURE_SECRET", "s3cret")
    app = main.create_app()
    raw = json.dumps({"event": "message.received", "text": "שלום"}, ensure_ascii=False).encode()
    sig = "sha256=" + hmac.new(b"s3cret", raw, hashlib.sha256).hexdigest()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/webhooks/kid-a", content=raw, headers={"X-OpenWA-Signature": sig})
    assert r.json() == {"ok": True}
    _assert_saved(tmp_path)
