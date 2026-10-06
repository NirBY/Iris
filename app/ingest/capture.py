"""Dev-only raw webhook capture, mounted when IRIS_CAPTURE_DIR is set.

Stores each delivery (headers + body) as a JSON file so real OpenWA payloads can be
sanitized into test fixtures. Replaced by the real ingest endpoint; never enable in production.
"""

import asyncio
import hashlib
import hmac
import json
import os
import re
import time
from pathlib import Path

from fastapi import APIRouter, Request

router = APIRouter()


def _write(capture_dir: Path, label: str, record: dict[str, object]) -> None:
    capture_dir.mkdir(parents=True, exist_ok=True)
    name = f"{int(time.time() * 1000)}-{label}.json"
    (capture_dir / name).write_text(json.dumps(record, ensure_ascii=False, indent=2))


_LABEL = re.compile(r"^[A-Za-z0-9_-]{1,32}$")


@router.post("/webhooks/{label}")
async def capture(label: str, request: Request) -> dict[str, bool]:
    capture_dir = Path(os.environ["IRIS_CAPTURE_DIR"])
    if not _LABEL.match(label):
        return {"ok": False}
    raw = await request.body()
    secret = os.environ.get("IRIS_CAPTURE_SECRET", "")
    got = request.headers.get("x-openwa-signature", "")
    expected = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    try:
        body: object = json.loads(raw)
    except ValueError:
        body = raw.decode(errors="replace")
    record = {
        "label": label,
        "headers": dict(request.headers),
        "signature_valid": bool(secret) and hmac.compare_digest(got, expected),
        "body": body,
    }
    await asyncio.to_thread(_write, capture_dir, label, record)
    return {"ok": True}
